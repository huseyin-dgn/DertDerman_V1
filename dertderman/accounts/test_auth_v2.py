from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import USER_LOGIN_ERROR, UserAuthenticationForm
from accounts.models import User
from companies.forms import COMPANY_LOGIN_ERROR
from companies.models import Company, CompanyMembership
from adminx.auth_views import LOGIN_ERROR


class AuthExperienceV2Tests(TestCase):
    password = 'AuthExperience2026!'

    @classmethod
    def setUpTestData(cls):
        cls.users = {role: User.objects.create_user(username=f'auth-v2-{role.lower()}',
            email=f'auth-v2-{role.lower()}@example.com', password=cls.password, user_type=role)
            for role in ['USER', 'COMPANY', 'ADMIN']}
        cls.company = Company.objects.create(name='Auth V2 Company', is_verified=True)
        cls.membership = CompanyMembership.objects.create(company=cls.company, user=cls.users['COMPANY'], role='OWNER')

    def test_all_nine_credential_role_combinations(self):
        routes = {'USER': 'accounts:login', 'COMPANY': 'company_auth:login', 'ADMIN': 'adminx:login'}
        destinations = {'USER': 'dashboard:home', 'COMPANY': 'companies:company_panel', 'ADMIN': 'adminx:home'}
        errors = {'USER': USER_LOGIN_ERROR, 'COMPANY': COMPANY_LOGIN_ERROR, 'ADMIN': LOGIN_ERROR}
        for source, account in self.users.items():
            for target, route in routes.items():
                with self.subTest(source=source, target=target):
                    client = Client()
                    identifier = {'email': account.email} if target == 'COMPANY' else {'username': account.username}
                    response = client.post(reverse(route), {**identifier, 'password': self.password,
                        'user_type': target, 'next': 'https://example.com/unsafe'})
                    if source == target:
                        self.assertRedirects(response, reverse(destinations[target]))
                        self.assertEqual(int(client.session['_auth_user_id']), account.pk)
                    else:
                        self.assertContains(response, errors[target])
                        self.assertNotIn('_auth_user_id', client.session)
                        self.assertNotContains(response, self.password)
                    self.assertIn('no-store', response['Cache-Control'])

    def test_company_access_conditions_each_fail_closed(self):
        cases = [(self.company, 'approval_status', 'PENDING'),
                 (self.company, 'approval_status', 'REJECTED'),
                 (self.company, 'is_active', False), (self.company, 'is_verified', False),
                 (self.company, 'archived_at', timezone.now()),
                 (self.membership, 'is_active', False), (self.membership, 'role', 'UNKNOWN'),
                 (self.users['COMPANY'], 'is_active', False)]
        for record, field, value in cases:
            with self.subTest(model=record.__class__.__name__, field=field, value=value):
                original = getattr(record, field)
                type(record).objects.filter(pk=record.pk).update(**{field: value})
                client = Client()
                response = client.post(reverse('company_auth:login'), {
                    'email': self.users['COMPANY'].email, 'password': self.password})
                self.assertContains(response, COMPANY_LOGIN_ERROR)
                self.assertNotIn('_auth_user_id', client.session)
                type(record).objects.filter(pk=record.pk).update(**{field: original})

    def test_user_wrong_unknown_inactive_and_wrong_role_share_generic_error(self):
        for username, password in [(self.users['USER'].username, 'wrong'), ('missing-auth-account', self.password),
                                   (self.users['ADMIN'].username, self.password), (self.users['COMPANY'].username, self.password)]:
            response = self.client.post(reverse('accounts:login'), {'username': username, 'password': password})
            self.assertContains(response, USER_LOGIN_ERROR)
            self.assertNotIn('_auth_user_id', self.client.session)
        self.users['USER'].is_active = False
        self.users['USER'].save(update_fields=['is_active'])
        response = self.client.post(reverse('accounts:login'), {
            'username': self.users['USER'].username, 'password': self.password})
        self.assertContains(response, USER_LOGIN_ERROR)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_user_role_is_checked_after_password_authentication(self):
        form = UserAuthenticationForm(data={'username': self.users['COMPANY'].username, 'password': self.password})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [USER_LOGIN_ERROR])

    def test_user_registration_ignores_all_privileged_fields_and_creates_no_company(self):
        companies, memberships = Company.objects.count(), CompanyMembership.objects.count()
        for role in ['ADMIN', 'COMPANY']:
            client = Client()
            response = client.post(reverse('accounts:register'), {
                'username': f'register-{role}', 'email': f'register-{role}@example.com',
                'password1': self.password, 'password2': self.password,
                'user_type': role, 'is_staff': 'true', 'is_superuser': 'true',
                'is_verified': 'true', 'approval_status': 'APPROVED', 'company_name': 'Injected company'})
            self.assertRedirects(response, reverse('dashboard:home'))
            account = User.objects.get(username=f'register-{role}')
            self.assertEqual(account.user_type, 'USER')
            self.assertFalse(account.is_staff or account.is_superuser or account.is_verified)
            self.assertTrue(account.check_password(self.password))
        self.assertEqual(Company.objects.count(), companies)
        self.assertEqual(CompanyMembership.objects.count(), memberships)

    def test_company_registration_preserves_architecture_and_confirmation(self):
        response = self.client.post(reverse('company_auth:register'), {
            'company_name': 'New Auth Company', 'first_name': 'Deniz', 'last_name': 'Yılmaz',
            'email': 'new-auth-company@example.com', 'phone': '5551234567',
            'password1': self.password, 'password2': self.password,
            'username': 'injected-username', 'user_type': 'ADMIN', 'role': 'MANAGER',
            'is_staff': 'true', 'is_superuser': 'true', 'is_verified': 'true',
            'approval_status': 'APPROVED', 'is_active': 'true'}, follow=True)
        self.assertContains(response, 'Şirket başvurunuz alındı.')
        self.assertContains(response, 'Başvurunuz yönetim ekibi tarafından incelendikten sonra')
        self.assertContains(response, 'ax-application-success')
        account = User.objects.get(email='new-auth-company@example.com')
        membership = account.company_memberships.get()
        company = membership.company
        self.assertEqual(account.user_type, 'COMPANY')
        self.assertNotEqual(account.username, 'injected-username')
        self.assertTrue(account.check_password(self.password))
        self.assertFalse(account.is_staff or account.is_superuser or account.is_verified)
        self.assertEqual(membership.role, 'OWNER')
        self.assertFalse(membership.is_active)
        self.assertEqual(company.approval_status, 'PENDING')
        self.assertFalse(company.is_active or company.is_verified)
        self.assertNotIn('password', [field.name for field in Company._meta.fields])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_csrf_required_on_all_five_auth_endpoints(self):
        for name in ['accounts:login', 'accounts:register', 'company_auth:login', 'company_auth:register', 'adminx:login']:
            client = Client(enforce_csrf_checks=True)
            self.assertEqual(client.post(reverse(name), {}).status_code, 403)
            self.assertNotIn('_auth_user_id', client.session)

    def test_auth_templates_have_real_fields_errors_and_role_links(self):
        for name in ['accounts:login', 'accounts:register', 'company_auth:login', 'company_auth:register']:
            response = self.client.get(reverse(name))
            self.assertTemplateUsed(response, 'layouts/auth_base.html')
            self.assertContains(response, 'data-password-toggle')
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertNotContains(response, 'name="user_type"')
            self.assertNotContains(response, 'name="is_staff"')
        response = self.client.get(reverse('company_auth:login'))
        self.assertContains(response, 'name="email"')
        self.assertNotContains(response, 'name="username"')
        self.assertContains(response, f'href="{reverse("accounts:login")}"')
        self.assertContains(self.client.get(reverse('accounts:login')), f'href="{reverse("company_auth:login")}"')
        response = self.client.post(reverse('accounts:register'), {'username': '<script>alert(1)</script>',
            'email': 'not-an-email', 'password1': '123', 'password2': 'different'})
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="id_password1_helptext"')
        self.assertContains(response, 'id="id_password2_error"')
        self.assertNotContains(response, '<script>alert(1)</script>')

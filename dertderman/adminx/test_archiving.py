from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from blog.models import Post
from companies.models import Company, CompanyMembership, CompanyNotification, CompanyResponse, InternalCompanyNote
from companies.services import active_company_memberships_for
from complaints.models import Complaint
from .forms import CompanyContentForm
from .services import archive_company


class ArchiveSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="archive-admin", email="admin-archive@example.com", user_type="ADMIN")
        cls.reader = User.objects.create_user(username="archive-reader", email="reader-archive@example.com")
        cls.agent = User.objects.create_user(username="archive-agent", email="agent-archive@example.com", user_type="COMPANY", password="ArchiveQA2026!")
        cls.company = Company.objects.create(name="Archive company", is_verified=True)
        cls.membership = CompanyMembership.objects.create(company=cls.company, user=cls.agent, role="OWNER")
        cls.complaint = Complaint.objects.create(company=cls.company, user=cls.reader, title="History to keep", description="Complaint body", status="PUBLISHED")
        cls.response = CompanyResponse.objects.create(company=cls.company, complaint=cls.complaint, author_user=cls.agent, body="Company response")
        cls.note = InternalCompanyNote.objects.create(company=cls.company, complaint=cls.complaint, author_user=cls.agent, body="Internal note")
        cls.post = Post.objects.create(title="Archived article", excerpt="Summary", content="Full content", author=cls.admin, status="PUBLISHED")

    def setUp(self):
        self.blog_url = reverse('adminx:blog_delete', args=[self.post.pk])
        self.company_url = reverse('adminx:company_archive', args=[self.company.pk])
        self.client.force_login(self.admin)

    def test_admin_blog_delete_preserves_record_and_removes_all_public_access(self):
        response = self.client.post(self.blog_url, follow=True)
        self.assertContains(response, 'Blog yazısı silindi.')
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, 'ARCHIVED')
        self.assertEqual(self.post.content, 'Full content')
        self.assertEqual(self.post.author, self.admin)
        for url in ['/', '/blog/']:
            self.assertNotContains(Client().get(url), self.post.title)
        for headers in [{}, {"HTTP_X_ARTICLE_READER": "1"}]:
            self.assertEqual(Client().get(reverse('blog:detail', args=[self.post.slug]), **headers).status_code, 404)
        self.assertNotContains(self.client.get(reverse('adminx:blog_list')), self.post.title)
        self.assertContains(self.client.get(reverse('adminx:blog_list'), {"status": "ARCHIVED"}), self.post.title)

    def test_archived_blog_cannot_be_republished_or_edited_via_old_endpoints(self):
        self.client.post(self.blog_url)
        for route in ['blog_edit', 'blog_publish']:
            response = self.client.post(reverse(f'adminx:{route}', args=[self.post.pk]), {"title": "Revived", "content": "New", "excerpt": "New"})
            self.assertEqual(response.status_code, 404)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, 'ARCHIVED')

    def test_user_company_unknown_and_staff_roles_cannot_archive(self):
        unknown = User.objects.create_user(username="unknown-archive", email="unknown@example.com", user_type="UNKNOWN")
        self.reader.is_staff = self.reader.is_superuser = True
        self.reader.save()
        for user in [self.reader, self.agent, unknown]:
            self.client.force_login(user)
            for url in [self.blog_url, self.company_url]:
                self.assertEqual(self.client.post(url).status_code, 403)
        self.post.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.post.status, 'PUBLISHED')
        self.assertTrue(self.company.is_active)
        self.assertIsNone(self.company.archived_at)

    def test_anonymous_and_logged_out_sessions_are_denied(self):
        old_session = self.client.cookies['sessionid'].value
        self.client.post(reverse('accounts:logout'))
        for replay in [False, True]:
            if replay:
                self.client.cookies['sessionid'] = old_session
            for url in [self.blog_url, self.company_url]:
                self.assertEqual(self.client.post(url).status_code, 302)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)

    def test_get_head_put_delete_never_change_state(self):
        for method in ['get', 'head', 'put', 'delete']:
            for url in [self.blog_url, self.company_url]:
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.post.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.post.status, 'PUBLISHED')
        self.assertTrue(self.company.is_active)

    def test_csrf_is_required_for_both_actions(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for url in [self.blog_url, self.company_url]:
            self.assertEqual(client.post(url).status_code, 403)
        self.company.refresh_from_db()
        self.post.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertEqual(self.post.status, 'PUBLISHED')
        client.get(reverse('adminx:company_edit', args=[self.company.pk]))
        for url in [self.blog_url, self.company_url]:
            self.assertEqual(client.post(url, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code, 302)

    def test_company_archive_preserves_all_relations_and_denies_existing_session(self):
        company_client = Client()
        company_client.force_login(self.agent)
        self.assertEqual(company_client.get(reverse('companies:company_panel')).status_code, 200)
        notification_ids = list(CompanyNotification.objects.filter(company=self.company).values_list('pk', flat=True))
        result = self.client.post(self.company_url)
        self.assertEqual(result.status_code, 302)
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_active)
        self.assertIsNotNone(self.company.archived_at)
        self.assertEqual(self.company.approval_status, 'APPROVED')
        for model, record in [(Complaint, self.complaint), (CompanyMembership, self.membership), (CompanyResponse, self.response), (InternalCompanyNote, self.note)]:
            self.assertTrue(model.objects.filter(pk=record.pk, company=self.company).exists())
        self.assertEqual(CompanyNotification.objects.filter(pk__in=notification_ids).count(), len(notification_ids))
        self.assertTrue(CompanyNotification.objects.filter(company=self.company, kind='ADMIN', title='Şirket arşivlendi.').exists())
        self.assertEqual(company_client.get(reverse('companies:company_panel')).status_code, 403)
        self.assertEqual(company_client.get(reverse('companies:complaint_detail', args=[self.complaint.pk])).status_code, 403)
        self.assertEqual(company_client.post(reverse('companies:response_create', args=[self.complaint.pk]), {"body": "No access"}).status_code, 403)
        self.assertFalse(active_company_memberships_for(self.agent).exists())
        self.assertEqual(Client().get(reverse('companies_public:company_detail', args=[self.company.slug])).status_code, 404)
        self.assertNotContains(Client().get('/sirketler/'), self.company.name)
        self.assertContains(self.client.get(reverse('adminx:company_edit', args=[self.company.pk])), self.company.name)

    def test_company_email_password_login_fails_after_archive(self):
        self.client.post(self.company_url)
        client = Client()
        response = client.post(reverse('company_auth:login'), {"email": self.agent.email, "password": "ArchiveQA2026!"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn('_auth_user_id', client.session)

    def test_archive_marker_denies_access_even_if_active_flag_is_reset(self):
        self.client.post(self.company_url)
        Company.objects.filter(pk=self.company.pk).update(is_active=True)
        self.assertFalse(active_company_memberships_for(self.agent).exists())
        company_client = Client()
        company_client.force_login(self.agent)
        for route in ['company_panel', 'profile', 'members', 'notifications', 'responses']:
            self.assertEqual(company_client.get(reverse(f'companies:{route}')).status_code, 403)
        client = Client()
        response = client.post(reverse('company_auth:login'), {
            'email': self.agent.email, 'password': 'ArchiveQA2026!',
        })
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn('_auth_user_id', client.session)

    def test_stale_company_content_edit_does_not_undo_archive(self):
        original_save = CompanyContentForm.save

        def archive_before_save(form, *args, **kwargs):
            archive_company(pk=self.company.pk, actor=self.admin)
            return original_save(form, *args, **kwargs)

        with patch.object(CompanyContentForm, 'save', archive_before_save):
            response = self.client.post(reverse('adminx:company_edit', args=[self.company.pk]), {
                'name': 'Updated company', 'description': 'Updated description',
                'is_active': 'on', 'archived_at': '',
            })
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, 'Updated company')
        self.assertFalse(self.company.is_active)
        self.assertIsNotNone(self.company.archived_at)

    def test_other_memberships_remain_available_and_post_body_cannot_choose_target(self):
        other = Company.objects.create(name="Other active company", is_verified=True)
        CompanyMembership.objects.create(user=self.agent, company=other, role="OWNER")
        self.client.post(self.company_url, {"company_id": other.pk, "next": "https://example.com/"})
        other.refresh_from_db()
        self.assertTrue(other.is_active)
        self.assertEqual(list(active_company_memberships_for(self.agent).values_list('company_id', flat=True)), [other.pk])
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(reverse('adminx:company_archive', args=[other.pk])).status_code, 403)

    def test_archived_pending_application_cannot_be_approved(self):
        Company.objects.filter(pk=self.company.pk).update(approval_status='PENDING')
        self.client.post(self.company_url)
        response = self.client.post(reverse('adminx:company_application_detail', args=[self.company.pk]), {"action": "approve"})
        self.assertEqual(response.status_code, 409)
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_active)

    def test_duplicate_actions_are_idempotent_and_missing_objects_are_404(self):
        for url in [self.blog_url, self.company_url]:
            self.assertEqual(self.client.post(url).status_code, 302)
            self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(CompanyNotification.objects.filter(company=self.company, title='Şirket arşivlendi.').count(), 1)
        for route in ['blog_delete', 'company_archive']:
            self.assertEqual(self.client.post(reverse(f'adminx:{route}', args=[999999])).status_code, 404)

    def test_admin_action_forms_have_csrf_confirmation_and_no_get_action(self):
        for route in ['company_list', 'blog_list']:
            response = self.client.get(reverse(f'adminx:{route}'))
            self.assertContains(response, 'data-confirm-action=')
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(self.client.get(reverse('adminx:company_list')), f'action="{self.company_url}"')
        self.assertContains(self.client.get(reverse('adminx:blog_list')), f'action="{self.blog_url}"')

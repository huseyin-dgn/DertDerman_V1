from datetime import timedelta
from django.contrib.auth.models import AnonymousUser
from django.db import connection, transaction
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from complaints.anti_abuse import FORM_SESSION_KEY
from accounts.models import User
from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanyNotification,
    CompanyNotificationRead,
    CompanyResponse,
)
from companies.panel_events import record_complaint_notification
from companies.panel_selectors import company_notifications
from companies.panel_services import create_company_entry
from companies.services import decide_company_application
from complaints.models import Complaint
from .models import Notification
from .selectors import inbox
from .services import mark_read, send


class NotificationCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='inbox-user', email='inbox-user@example.com', user_type='USER')
        cls.other = User.objects.create_user(username='other-user', email='other-user@example.com', user_type='USER')
        cls.admin = User.objects.create_user(username='inbox-admin', email='inbox-admin@example.com', user_type='ADMIN')
        cls.admin2 = User.objects.create_user(username='other-admin', email='other-admin@example.com', user_type='ADMIN')
        cls.agent = User.objects.create_user(username='inbox-company', email='inbox-company@example.com', user_type='COMPANY')
        cls.colleague = User.objects.create_user(username='colleague', email='colleague@example.com', user_type='COMPANY')
        cls.company_category = CompanyCategory.objects.create(
            name="Test Kategorisi"
        )
        cls.company = Company.objects.create(name='Inbox Company', is_verified=True)
        cls.foreign_company = Company.objects.create(name='Foreign Company', is_verified=True)
        cls.member = CompanyMembership.objects.create(user=cls.agent, company=cls.company, role='OWNER')
        CompanyMembership.objects.create(user=cls.colleague, company=cls.company)
        CompanyMembership.objects.create(user=cls.agent, company=cls.foreign_company)
        cls.complaint = Complaint.objects.create(user=cls.user, company=cls.company,
            title='Bildirim testi', description='Bildirim merkezi için yeterli uzunlukta açıklama.')
        cls.foreign = Complaint.objects.create(user=cls.other, company=cls.foreign_company,
            title='Foreign complaint', description='Another complaint description for security tests.')

    def login(self, user):
        self.client.force_login(user)
        if user.user_type == 'COMPANY':
            session = self.client.session
            session['company_panel_company_id'] = self.company.pk
            session.save()

    def test_create_workflow_and_rapid_repeated_post(self):
        self.user.is_verified = True
        self.user.save(
            update_fields=["is_verified"]
        )
        Complaint.objects.filter(
                pk=self.complaint.pk
            ).update(
                created_at=(
                    timezone.now()
                    - timedelta(minutes=31)
                )
            )

        self.login(self.user)

        route = reverse(
            "complaints:create"
        )

        data = {
            "company": self.company.pk,
            "category": Complaint.Category.OTHER,
            "title": "Yeni şikayet başlığı",
            "description": (
                "Yeterli uzunlukta gerçek "
                "şikayet açıklaması."
            ),
        }

        # Gerçek kullanıcı akışını taklit et:
        # önce form açılır.
        self.client.get(route)

        session = self.client.session
        session[FORM_SESSION_KEY] = (
            timezone.now()
            - timedelta(seconds=2)
        ).timestamp()
        session.save()

        first_response = self.client.post(
            route,
            data,
        )

        self.assertEqual(
            first_response.status_code,
            302,
        )

        # Kullanıcı ikinci kez formu açıyor.
        self.client.get(route)

        session = self.client.session
        session[FORM_SESSION_KEY] = (
            timezone.now()
            - timedelta(seconds=2)
        ).timestamp()
        session.save()

        # Aynı şikayeti tekrar göndermeye çalışıyor.
        second_response = self.client.post(
            route,
            data,
        )

        self.assertEqual(
            second_response.status_code,
            429,
        )

        complaint = Complaint.objects.get(
            title=data["title"]
        )

        self.assertEqual(
            Notification.objects.filter(
                complaint=complaint,
                notification_type="RECEIVED",
            ).count(),
            1,
        )

        self.assertEqual(
            Notification.objects.filter(
                complaint=complaint,
                notification_type="MODERATION",
            ).count(),
            2,
        )

        self.assertEqual(
            complaint.company_notifications.filter(
                kind="NEW"
            ).count(),
            1,
        )
    def test_publish_real_workflow_notifies_owner_company_and_retry_is_noop(self):
        self.login(self.admin)
        route = reverse('adminx:complaint_publish', args=[self.complaint.pk])
        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(self.client.post(route).status_code, 409)
        notice = Notification.objects.get(complaint=self.complaint, notification_type='PUBLISHED')
        self.assertEqual(notice.recipient_user, self.user)
        self.assertEqual(notice.target_url, reverse('complaints:detail', args=[self.complaint.pk]))
        self.assertEqual(self.complaint.company_notifications.filter(kind='PUBLISHED').count(), 1)

    def test_rejection_resolution_and_repeated_legitimate_transition(self):
        self.login(self.admin)
        self.client.post(reverse('adminx:complaint_reject', args=[self.complaint.pk]))
        self.assertTrue(Notification.objects.filter(complaint=self.complaint, notification_type='REJECTED').exists())
        self.complaint.refresh_from_db()
        for status in ['RESOLVED', 'PUBLISHED', 'RESOLVED']:
            self.complaint.status = status
            self.complaint.save(update_fields=['status'])
            self.complaint.save(update_fields=['status'])
        self.assertEqual(Notification.objects.filter(complaint=self.complaint, notification_type='RESOLVED').count(), 2)
        self.assertEqual(self.complaint.company_notifications.filter(kind='RESOLVED').count(), 2)

    def test_event_service_retries_and_partial_saves(self):
        record_complaint_notification(self.complaint, 'NEW')
        record_complaint_notification(self.complaint, 'NEW')
        self.assertEqual(self.complaint.company_notifications.filter(kind='NEW').count(), 1)
        self.assertEqual(Notification.objects.filter(complaint=self.complaint, notification_type='RECEIVED').count(), 1)
        self.complaint.status = 'RESOLVED'
        self.complaint.save(update_fields=['title'])
        self.assertFalse(Notification.objects.filter(complaint=self.complaint, notification_type='RESOLVED').exists())

    def test_response_post_notifies_owner_once_and_later_same_text_is_allowed(self):
        self.login(self.agent)
        route = reverse('companies:response_create', args=[self.complaint.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(route, {'body': 'Çözüm için sizinle iletişime geçiyoruz.'}).status_code, 302)
        response = CompanyResponse.objects.get(complaint=self.complaint)
        notice = Notification.objects.get(complaint=self.complaint, notification_type='RESPONSE')
        self.assertEqual(notice.recipient_user, self.user)
        CompanyResponse.objects.filter(pk=response.pk).update(created_at=timezone.now() - timedelta(minutes=1))
        self.client.post(route, {'body': response.body})
        self.assertEqual(Notification.objects.filter(complaint=self.complaint, notification_type='RESPONSE').count(), 2)
        self.login(self.user)
        self.assertContains(self.client.get(notice.target_url), response.body)

    def test_internal_notes_never_notify_consumers(self):
        count = Notification.objects.count()
        create_company_entry(user=self.agent, company_id=self.company.pk, complaint_id=self.complaint.pk,
                             body='Sadece ekip içinde kalacak not.', internal=True)
        self.assertEqual(Notification.objects.count(), count)

    def test_company_application_real_form_admin_notifications_and_owner_approval(self):
        response = self.client.post(reverse('company_auth:register'), {
            'company_name': 'Notification Application', 'first_name': 'Deniz', 'last_name': 'Yılmaz',
            'email': 'notification-application@example.com', 'phone': '5551234567',
            'password1': 'RiverMountain2026!safe', 'password2': 'RiverMountain2026!safe' , 'category': self.company_category.pk,})
        self.assertEqual(response.status_code, 302)
        company = Company.objects.get(name='Notification Application')
        self.assertEqual(Notification.objects.filter(company=company, notification_type='APPLICATION').count(), 2)
        notice = Notification.objects.get(company=company, recipient_user=self.admin)
        self.assertEqual(notice.target_url, reverse('adminx:company_application_detail', args=[company.pk]))
        decide_company_application(company.pk, 'APPROVED')
        decide_company_application(company.pk, 'APPROVED')
        owner = company.memberships.get(role='OWNER').user
        self.assertEqual(company_notifications(company, owner).filter(kind='ADMIN').count(), 1)
        self.assertIn('onaylandı', company_notifications(company, owner).get().title)

    def test_rollback_removes_notifications_with_business_records(self):
        count = Notification.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Complaint.objects.create(user=self.user, company=self.company, title='Rollback event', description='Rollback test description.')
                raise RuntimeError('rollback')
        self.assertEqual(Notification.objects.count(), count)

    def test_user_idor_read_and_get_never_marks_read(self):
        self.login(self.user)
        mine = inbox(self.user, 'USER').first()
        foreign = inbox(self.other, 'USER').first()
        self.assertEqual(self.client.get(reverse('notifications:open', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('notifications:read', args=[foreign.pk])).status_code, 404)
        self.client.get(reverse('notifications:list'))
        self.client.get(reverse('notifications:open', args=[mine.pk]))
        mine.refresh_from_db()
        self.assertFalse(mine.is_read)
        self.assertEqual(self.client.get(reverse('notifications:read', args=[mine.pk])).status_code, 405)
        self.client.post(reverse('notifications:read', args=[mine.pk]), {'target_url': 'https://example.com'})
        mine.refresh_from_db()
        self.assertTrue(mine.is_read)
        first_read = mine.read_at
        self.client.post(reverse('notifications:read', args=[mine.pk]))
        mine.refresh_from_db()
        self.assertEqual(mine.read_at, first_read)

    def test_company_idor_and_mark_all_selected_scope_personal_reads(self):
        self.login(self.agent)
        mine = self.complaint.company_notifications.first()
        foreign = self.foreign.company_notifications.first()
        self.assertEqual(self.client.get(reverse('companies:notification_open', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('companies:notification_read', args=[foreign.pk])).status_code, 404)
        route = reverse('companies:notifications_read_all')
        self.assertEqual(self.client.get(route).status_code, 405)
        self.assertEqual(self.client.post(route, {'company_id': self.foreign_company.pk}).status_code, 302)
        self.assertTrue(CompanyNotificationRead.objects.filter(notification=mine, user=self.agent).exists())
        self.assertFalse(CompanyNotificationRead.objects.filter(notification=foreign, user=self.agent).exists())
        self.assertFalse(CompanyNotificationRead.objects.filter(user=self.colleague).exists())

    def test_revoked_company_access_and_transferred_complaint_are_hidden(self):
        self.login(self.agent)
        mine = self.complaint.company_notifications.first()
        Complaint.objects.filter(pk=self.complaint.pk).update(company=self.foreign_company)
        self.assertEqual(self.client.post(reverse('companies:notification_read', args=[mine.pk])).status_code, 404)
        self.member.is_active = False
        self.member.save()
        self.assertFalse(company_notifications(self.company, self.agent).exists())
        self.assertFalse(company_notifications(self.company, AnonymousUser()).exists())

    def test_user_ownership_transfer_hides_old_notification(self):
        mine = inbox(self.user, 'USER').first()
        Complaint.objects.filter(pk=mine.complaint_id).update(user=self.other)
        self.login(self.user)
        self.assertEqual(self.client.get(reverse('notifications:open', args=[mine.pk])).status_code, 404)

    def test_admin_scope_and_personal_reads(self):
        self.login(self.admin)
        other = inbox(self.admin2, 'ADMIN').first()
        user_notice = inbox(self.user, 'USER').first()
        for notice in [other, user_notice]:
            self.assertEqual(self.client.get(reverse('adminx:notification_open', args=[notice.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse('adminx:notification_read', args=[notice.pk])).status_code, 404)
        self.client.post(reverse('adminx:notifications_read_all'))
        self.assertFalse(inbox(self.admin, 'ADMIN').filter(is_read=False).exists())
        self.assertTrue(inbox(self.admin2, 'ADMIN').filter(is_read=False).exists())
        self.assertTrue(inbox(self.user, 'USER').filter(is_read=False).exists())

    def test_all_role_combinations_and_anonymous_access(self):
        routes = {'USER': 'notifications:list', 'ADMIN': 'adminx:notifications', 'COMPANY': 'companies:notifications'}
        for target, route in routes.items():
            self.assertEqual(self.client.get(reverse(route)).status_code, 302)
            for user in [self.user, self.agent, self.admin]:
                self.login(user)
                self.assertEqual(self.client.get(reverse(route)).status_code, 200 if user.user_type == target else 403)
            self.client.logout()

    def test_csrf_and_post_for_all_read_actions(self):
        for user, namespace, single, all_name, pk in [
            (self.user, 'notifications', 'read', 'read_all', inbox(self.user, 'USER').first().pk),
            (self.admin, 'adminx', 'notification_read', 'notifications_read_all', inbox(self.admin, 'ADMIN').first().pk),
            (self.agent, 'companies', 'notification_read', 'notifications_read_all', self.complaint.company_notifications.first().pk)]:
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            for route in [reverse(f'{namespace}:{single}', args=[pk]), reverse(f'{namespace}:{all_name}')]:
                self.assertEqual(client.post(route).status_code, 403)
                self.assertEqual(client.get(route).status_code, 405)

    def test_pagination_unread_first_newest_first_and_admin_preview(self):
        Notification.objects.all().delete()
        CompanyNotification.objects.all().delete()
        for i in range(19):
            for user, scope in [(self.user, 'USER'), (self.admin, 'ADMIN')]:
                send(recipient=user, scope=scope, kind='UPDATED', event_key=f'test:{i}', title=f'Notice {i}')
            CompanyNotification.objects.create(company=self.company, kind='NEW', title=f'Notice {i}')
        for user, name, size in [(self.user, 'notifications:list', 8), (self.agent, 'companies:notifications', 8), (self.admin, 'adminx:notifications', 10)]:
            self.login(user)
            first = self.client.get(reverse(name)).context['page_obj']
            self.assertEqual(len(first), size)
            self.assertEqual(first[0].title, 'Notice 18')
            self.assertEqual(len(self.client.get(reverse(name), {'page': 2}).context['page_obj']), 9 if size == 10 else 8)
            for page in ['abc', -1, 999999]:
                self.assertEqual(self.client.get(reverse(name), {'page': page}).status_code, 200)
        mark_read(inbox(self.user, 'USER').filter(title='Notice 18'))
        self.login(self.user)
        self.assertEqual(self.client.get(reverse('notifications:list')).context['page_obj'][0].title, 'Notice 17')
        self.login(self.admin)
        self.assertEqual(len(self.client.get(reverse('adminx:home')).context['recent_notifications']), 5)
        mark_read(inbox(self.admin, 'ADMIN').filter(title='Notice 18'))
        self.assertEqual(self.client.get(reverse('adminx:notifications')).context['page_obj'][0].title, 'Notice 18')
        CompanyNotificationRead.objects.create(user=self.agent,
            notification=CompanyNotification.objects.get(company=self.company, title='Notice 18'))
        self.login(self.agent)
        self.assertEqual(self.client.get(reverse('companies:notifications')).context['page_obj'][0].title, 'Notice 18')

    def test_xss_safe_target_and_header_count(self):
        self.login(self.user)
        notice = send(recipient=self.user, scope='USER', kind='UPDATED', event_key='xss',
                      title='<script>alert(1)</script>', message='<img src=x onerror=alert(1)>')
        response = self.client.get(reverse('notifications:list'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(response.context['notification_unread_count'], inbox(self.user, 'USER').filter(is_read=False).count())
        self.assertEqual(self.client.post(reverse('notifications:read', args=[notice.pk]),
            {'next': '//evil.example', 'target_url': 'javascript:alert(1)'}).url, reverse('notifications:list'))

    def test_empty_states(self):
        Notification.objects.all().delete()
        CompanyNotification.objects.all().delete()
        for user, route, message in [(self.user, 'notifications:list', 'Henüz yeni bildiriminiz yok.'),
            (self.agent, 'companies:notifications', 'Şirketiniz için yeni bir bildirim bulunmuyor.'),
            (self.admin, 'adminx:notifications', 'İncelenecek yeni sistem bildirimi bulunmuyor.')]:
            self.login(user)
            self.assertContains(self.client.get(reverse(route)), message)

    def test_no_n_plus_one_and_header_count_does_not_load_objects(self):
        for _ in range(12):
            Complaint.objects.create(user=self.user, company=self.company, title='Query test', description='Query budget complaint description.')
        self.login(self.user)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse('notifications:list'))
        self.assertLessEqual(len(captured), 6)
        self.login(self.agent)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse('companies:notifications'))
        self.assertLessEqual(len(captured), 7)
        self.login(self.admin)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse('adminx:notifications'))
        self.assertLessEqual(len(captured), 6)

    def test_user_mark_all_preserves_other_users(self):
        self.login(self.user)
        self.client.post(reverse('notifications:read_all'))
        self.assertFalse(inbox(self.user, 'USER').filter(is_read=False).exists())
        self.assertTrue(inbox(self.other, 'USER').filter(is_read=False).exists())
        self.assertTrue(inbox(self.admin, 'ADMIN').filter(is_read=False).exists())

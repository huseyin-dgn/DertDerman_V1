from django.core.paginator import Paginator
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from companies.models import Company, CompanyMembership, CompanyResponse, InternalCompanyNote
from complaints.models import Complaint


class PaginationStandardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(username="paging-reader", email="paging@example.com")
        cls.agent = User.objects.create_user(username="paging-agent", email="agent@example.com", user_type="COMPANY")
        cls.company = Company.objects.create(name="Paging Company", is_verified=True)
        CompanyMembership.objects.create(user=cls.agent, company=cls.company, role="OWNER")
        cls.complaints = [Complaint.objects.create(user=cls.reader, company=cls.company,
            title=f"Paging {i}", description="Description", status="PUBLISHED") for i in range(19)]
        cls.responses = [CompanyResponse.objects.create(company=cls.company, complaint=cls.complaints[0],
            author_user=cls.agent, body=f"Response {i}") for i in range(19)]
        cls.notes = [InternalCompanyNote.objects.create(company=cls.company, complaint=cls.complaints[0],
            author_user=cls.agent, body=f"Private note {i}") for i in range(19)]

    def test_private_lists_and_dashboard_sizes(self):
        self.client.force_login(self.reader)
        page = self.client.get(reverse("complaints:list")).context["page_obj"]
        self.assertEqual(len(page), 6)
        self.assertEqual(page.paginator.count, 19)
        self.client.force_login(self.agent)
        for name, size in [("complaint_list", 6), ("responses", 6), ("notifications", 8)]:
            response = self.client.get(reverse(f"companies:{name}"))
            self.assertEqual(len(response.context["page_obj"]), size)
        response = self.client.get(reverse("companies:company_panel"))
        self.assertEqual(len(response.context["recent_complaints"]), 5)
        self.assertTemplateUsed(response, "layouts/company_base.html")

    def test_history_is_complete_paginated_and_keeps_independent_page_parameters(self):
        self.client.force_login(self.agent)
        url = reverse("companies:complaint_detail", args=[self.complaints[0].pk])
        first = self.client.get(url, {"response_page": 2, "note_page": 2})
        self.assertEqual(len(first.context["response_page"]), 6)
        self.assertEqual(len(first.context["note_page"]), 9)
        self.assertEqual(len(first.context["history"]), 10)
        self.assertContains(first, "response_page=2&amp;note_page=2&amp;history_page=2")
        count = first.context["history"].paginator.count
        seen = []
        for number in range(1, first.context["history"].paginator.num_pages + 1):
            history = self.client.get(url, {"history_page": number}).context["history"]
            seen.extend((x["source"], x["event_id"]) for x in history)
        self.assertEqual(len(seen), count)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(sum(source == "response" for source, _ in seen), 19)
        self.assertEqual(sum(source == "note" for source, _ in seen), 19)
        self.assertEqual(count, 39)

    def test_public_companies_are_eight_and_newest_first(self):
        companies = [Company.objects.create(name=f"Directory {i}") for i in range(18)]
        expected = [x.pk for x in reversed(companies)] + [self.company.pk]
        seen = []
        for number, size in [(1, 8), (2, 8), (3, 3)]:
            response = self.client.get(reverse("companies_public:company_list"), {"page": number})
            self.assertEqual(len(response.context["page_obj"]), size)
            seen.extend(x.pk for x in response.context["page_obj"])
        self.assertEqual(seen, expected)

    def test_public_response_pages_do_not_expose_internal_notes(self):
        response = self.client.get(reverse("complaints:public_detail", args=[self.complaints[0].pk]), {"response_page": 2})
        self.assertEqual(len(response.context["company_response_page"]), 6)
        self.assertNotContains(response, "Private note")

    def test_elided_pagination_preserves_repeated_query_values_and_escapes(self):
        request = RequestFactory().get('/?q=%22%3E%3Cscript%3E&tag=a&tag=b&note_page=3')
        page = Paginator(range(150), 5).get_page(15)
        html = Template("{% include 'components/pagination.html' %}").render(RequestContext(request, {"page_obj": page}))
        self.assertIn("…", html)
        self.assertIn('aria-current="page"', html)
        self.assertIn("tag=a&amp;tag=b&amp;note_page=3&amp;page=16", html)
        self.assertNotIn("<script>", html)

    def test_pagination_navigation_has_disabled_boundaries(self):
        request = RequestFactory().get('/')
        template = Template("{% include 'components/pagination.html' %}")
        html = template.render(RequestContext(request, {"page_obj": Paginator(range(2), 5).get_page(1)}))
        self.assertEqual(html.count('aria-disabled="true"'), 2)

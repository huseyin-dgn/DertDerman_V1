from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from accounts.models import User
from blog.models import Post
from companies.models import Company, CompanyCategory
from complaints.models import Complaint


class PublicExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CompanyCategory.objects.create(name="Teknoloji")
        cls.companies = [Company.objects.create(name=f"Rehber şirket {i}", category=cls.category,
            description=f"Şirket açıklaması {i}", is_verified=i % 2 == 0) for i in range(19)]
        cls.posts = [Post.objects.create(title=f"Rehber yazı {i}", excerpt=f"Okuma özeti {i}",
            content=f"YALNIZCA_DETAY_ICERIGI_{i}\n\nİkinci paragraf.", status="PUBLISHED", published_at=timezone.now()) for i in range(15)]
        stamp = timezone.now()
        Company.objects.all().update(created_at=stamp)
        Post.objects.all().update(published_at=stamp)
        cls.hidden_companies = [Company.objects.create(name=f"Gizli şirket {status}", approval_status=status,
            is_active=True, is_verified=True) for status in ["PENDING", "REJECTED"]]
        cls.hidden_companies.append(Company.objects.create(name="Pasif şirket", is_active=False))
        cls.hidden_companies.append(Company.objects.create(name="Arşivde şirket", archived_at=stamp))
        cls.hidden_posts = [Post.objects.create(title=f"Gizli yazı {status}", excerpt="Gizli özet", content="Gizli içerik", status=status) for status in ["DRAFT", "ARCHIVED"]]

    def test_company_pages_eight_newest_first_no_duplicates_or_skips(self):
        seen = []
        for page, size in [(1, 8), (2, 8), (3, 3)]:
            response = self.client.get(reverse("companies_public:company_list"), {"page": page})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context["page_obj"]), size)
            self.assertContains(response, 'class="directory-card"', count=size)
            seen += [item.pk for item in response.context["page_obj"]]
        self.assertEqual(seen, [item.pk for item in reversed(self.companies)])

    def test_public_visibility_is_explicit_and_verification_remains_a_badge(self):
        for company in self.hidden_companies:
            url = reverse("companies_public:company_detail", args=[company.slug])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertNotContains(self.client.get('/sirketler/', {"s": company.name}), company.name + '</a>')
            self.assertEqual(self.client.get('/sirketler/', {"s": company.name}).context["page_obj"].paginator.count, 0)
            self.assertNotContains(self.client.get('/'), company.name)
        unverified = self.companies[1]
        response = self.client.get('/sirketler/', {"s": unverified.name})
        self.assertContains(response, unverified.name)
        self.assertEqual(self.client.get(reverse("companies_public:company_detail", args=[unverified.slug])).status_code, 200)

    def test_search_is_applied_before_pagination_and_preserves_query(self):
        response = self.client.get('/sirketler/', {"s": "Teknoloji", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 8)
        self.assertEqual(response.context["page_obj"].paginator.count, 19)
        self.assertContains(response, 's=Teknoloji&amp;page=3')
        response = self.client.get('/sirketler/', {"q": "Rehber şirket 0"})
        self.assertEqual(list(response.context["page_obj"]), [self.companies[0]])
        self.assertNotContains(response, 'data-company-directory')

    def test_cards_only_count_published_complaints(self):
        reader = User.objects.create_user(username="count-reader", email="count@example.com")
        for status in Complaint.Status.values:
            Complaint.objects.create(company=self.companies[0], user=reader, title=status, description="Metin", status=status)
        response = self.client.get('/sirketler/', {"s": "Rehber şirket 0"})
        self.assertContains(response, "1 yayındaki şikayet")

    def test_blog_pages_six_and_no_article_bodies_in_list(self):
        seen = []
        for page, size in [(1, 6), (2, 6), (3, 3)]:
            response = self.client.get('/blog/', {"page": page})
            self.assertContains(response, 'class="journal-card"', count=size)
            self.assertNotContains(response, "YALNIZCA_DETAY_ICERIGI")
            self.assertContains(response, "data-article-link")
            seen += [item.pk for item in response.context["page_obj"]]
        self.assertEqual(seen, [post.pk for post in reversed(self.posts)])
        response = self.client.get('/blog/', {"s": "Rehber", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 6)
        self.assertContains(response, 's=Rehber&amp;page=3')

    def test_reader_fragment_and_direct_page_share_article_and_publication_policy(self):
        post = self.posts[0]
        url = reverse('blog:detail', args=[post.slug])
        direct = self.client.get(url)
        fragment = self.client.get(url, HTTP_X_ARTICLE_READER="1")
        for response in [direct, fragment]:
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, post.title)
            self.assertContains(response, post.excerpt)
            self.assertContains(response, "YALNIZCA_DETAY_ICERIGI_0")
            self.assertTemplateUsed(response, 'blog/article.html')
            self.assertIn('X-Article-Reader', response['Vary'])
        self.assertContains(direct, 'rel="canonical"')
        self.assertNotContains(fragment, '<html')
        for post in self.hidden_posts:
            for headers in [{}, {"HTTP_X_ARTICLE_READER": "1"}]:
                response = self.client.get(reverse('blog:detail', args=[post.slug]), **headers)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, post.content, status_code=404)

    def test_xss_is_escaped_in_cards_articles_and_search(self):
        attack = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
        Post.objects.filter(pk=self.posts[0].pk).update(title=attack, excerpt=attack, content=attack)
        url = reverse('blog:detail', args=[self.posts[0].slug])
        for response in [self.client.get('/blog/', {"s": '<img'}), self.client.get(url), self.client.get(url, HTTP_X_ARTICLE_READER='1')]:
            self.assertNotContains(response, attack)
            self.assertContains(response, escape(attack))
        response = self.client.get('/sirketler/', {"s": attack})
        self.assertNotContains(response, attack)
        self.assertContains(response, escape(attack))

    def test_invalid_pages_empty_states_and_query_counts(self):
        for url in ['/sirketler/', '/blog/']:
            for page in ['abc', '-5', '999999']:
                self.assertEqual(self.client.get(url, {"page": page}).status_code, 200)
            with CaptureQueriesContext(connection) as queries:
                self.client.get(url)
            self.assertEqual(len(queries), 2)
        self.assertContains(self.client.get('/sirketler/', {"s": 'olmayan'}), 'Aradığınız kriterlere uygun şirket bulunamadı.')
        self.assertContains(self.client.get('/blog/', {"s": 'olmayan'}), 'Aramanızla eşleşen bir yazı bulunamadı.')

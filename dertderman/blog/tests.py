import re
import struct
import tempfile
import zlib
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from PIL import Image

from companies.models import Company, CompanyCategory
from complaints.models import Complaint
from .forms import MAX_IMAGE_BYTES
from .models import Post


User = get_user_model()


def image_upload(fmt="PNG", name="cover.png", size=(32, 24)):
    stream = BytesIO()
    Image.new("RGB", size, "blue").save(stream, format=fmt)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


class BlogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="blog-admin", email="private-admin@example.com", user_type="ADMIN")
        cls.reader = User.objects.create_user(username="blog-reader", email="reader@example.com", user_type="USER")
        cls.company_user = User.objects.create_user(username="blog-company", email="company@example.com", user_type="COMPANY")
        cls.draft = Post.objects.create(title="Private draft title", excerpt="Private draft excerpt", content="Private draft body")
        cls.published = Post.objects.create(title="Published blog title", excerpt="Published excerpt", content="Public article body", status="PUBLISHED", published_at=timezone.now())

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.list_url = reverse("blog:list")
        self.admin_list = reverse("adminx:blog_list")
        self.create_url = reverse("adminx:blog_create")
        self.edit_url = reverse("adminx:blog_edit", args=[self.draft.pk])
        self.publish_url = reverse("adminx:blog_publish", args=[self.draft.pk])

    def data(self, **extra):
        return {"title": "New blog article", "excerpt": "An informative summary.", "content": "Longer article content for readers.", **extra}

    def test_publication_privacy_and_navbar(self):
        for url in [self.list_url, "/"]:
            response = self.client.get(url)
            self.assertContains(response, self.published.title)
            self.assertNotContains(response, self.draft.title)
            self.assertNotContains(response, self.admin.email)
            self.assertContains(response, 'href="/blog/"')
            self.assertNotIn("no-store", response.headers.get("Cache-Control", ""))
        for user in [None, self.admin]:
            if user:
                self.client.force_login(user)
            response = self.client.get(reverse("blog:detail", args=[self.draft.slug]))
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, self.draft.content, status_code=404)
        self.assertEqual(self.client.get(reverse("blog:detail", args=["missing"])).status_code, 404)
        self.assertContains(self.client.get(reverse("blog:detail", args=[self.published.slug])), self.published.content)

    def test_admin_role_matrix_and_no_unauthorized_mutation(self):
        for user in [None, self.reader, self.company_user, self.admin]:
            client = Client()
            if user:
                client.force_login(user)
            for url in [self.admin_list, self.create_url, self.edit_url]:
                response = client.get(url)
                self.assertEqual(response.status_code, 302 if user is None else 200 if user == self.admin else 403)
                if user == self.admin:
                    self.assertIn("no-store", response["Cache-Control"])
            if user != self.admin:
                for url in [self.create_url, self.edit_url, self.publish_url]:
                    self.assertEqual(client.post(url, self.data(status="PUBLISHED")).status_code, 302 if user is None else 403)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "DRAFT")
        self.assertEqual(Post.objects.count(), 2)

    def test_create_ignores_privileged_metadata_and_defaults_to_draft(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.create_url, self.data(status="PUBLISHED", published_at="2020-01-01", author=self.reader.pk, slug="attacker-slug"))
        post = Post.objects.get(title="New blog article")
        self.assertRedirects(response, reverse("adminx:blog_edit", args=[post.pk]))
        self.assertEqual(post.status, "DRAFT")
        self.assertIsNone(post.published_at)
        self.assertNotEqual(post.slug, "attacker-slug")

    def test_edit_allowlist_slug_stability_and_published_metadata(self):
        self.client.force_login(self.admin)
        post = self.published
        slug, published_at = post.slug, post.published_at
        response = self.client.post(reverse("adminx:blog_edit", args=[post.pk]), self.data(status="DRAFT", slug="new-slug", published_at="2020-01-01"))
        self.assertEqual(response.status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.title, "New blog article")
        self.assertEqual(post.status, "PUBLISHED")
        self.assertEqual(post.slug, slug)
        self.assertEqual(post.published_at, published_at)

    def test_publish_post_csrf_and_double_submit(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.get(self.publish_url).status_code, 405)
        self.assertEqual(client.post(self.publish_url).status_code, 403)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "DRAFT")
        response = client.get(self.edit_url)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)
        self.assertRedirects(client.post(self.publish_url, {"csrfmiddlewaretoken": token, "status": "DRAFT"}), self.edit_url)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "PUBLISHED")
        self.assertIsNotNone(self.draft.published_at)
        published_at = self.draft.published_at
        self.assertEqual(client.post(self.publish_url, {"csrfmiddlewaretoken": token}).status_code, 409)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.published_at, published_at)
        for url in [self.list_url, "/", reverse("blog:detail", args=[self.draft.slug])]:
            self.assertContains(Client().get(url), self.draft.title)

    def test_create_edit_require_csrf_and_invalid_forms_render_errors(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for url in [self.create_url, self.edit_url]:
            self.assertEqual(client.post(url, self.data()).status_code, 403)
        self.client.force_login(self.admin)
        for url in [self.create_url, self.edit_url]:
            response = self.client.post(url, {})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertContains(response, 'aria-invalid="true"')

    def test_pagination_order_invalid_pages_and_home_limit(self):
        posts = [Post.objects.create(title=f"Post {i:02d}", excerpt="Excerpt", content="Body", status="PUBLISHED", published_at=timezone.now()) for i in range(19)]
        seen = []
        for number, size in [(1, 6), (2, 6), (3, 6), (4, 2)]:
            response = self.client.get(self.list_url, {"page": number})
            objects = list(response.context["page_obj"])
            self.assertEqual(len(objects), size)
            seen += objects
        self.assertEqual(seen, list(reversed(posts)) + [self.published])
        for value, page in [("abc", 1), ("-1", 4), ("999999", 4)]:
            response = self.client.get(self.list_url, {"page": value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["page_obj"].number, page)
        self.assertEqual(list(self.client.get("/").context["recent_posts"]), list(reversed(posts))[:3])
        self.client.force_login(self.admin)
        response = self.client.get(self.admin_list, {"page": "abc"})
        self.assertEqual(len(response.context["page_obj"]), 5)

    def test_slug_collision_and_non_ascii_title(self):
        posts = [Post.objects.create(title=title, excerpt="Summary", content="Body") for title in ["Same Title", "Same Title", "你好"]]
        self.assertEqual(len({post.slug for post in posts}), 3)
        for post in posts:
            self.assertRegex(post.slug, r"^[a-z0-9-]+$")

    def test_plain_text_and_meta_are_escaped(self):
        self.published.title = '<script>alert(1)</script>'
        self.published.excerpt = '\"/><img src=x onerror=alert(2)>'
        self.published.content = '<script>alert(3)</script>\nAnother paragraph.'
        self.published.save()
        for url in [self.list_url, "/", reverse("blog:detail", args=[self.published.slug])]:
            response = self.client.get(url)
            self.assertContains(response, escape(self.published.title))
            self.assertNotContains(response, self.published.title)
            self.assertContains(response, escape(self.published.excerpt))
            self.assertNotContains(response, self.published.excerpt)
        self.assertContains(response, '<p>&lt;script&gt;alert(3)&lt;/script&gt;<br>Another paragraph.</p>', html=True)
        self.assertNotContains(response, self.published.content)

    def test_supported_images_are_normalized_and_names_are_generated(self):
        self.client.force_login(self.admin)
        for fmt in ["JPEG", "PNG", "WEBP"]:
            with self.subTest(fmt=fmt):
                upload = image_upload(fmt, name="../../untrusted.jpg", size=(2000, 1000))
                response = self.client.post(self.create_url, self.data(title=fmt, cover_image=upload))
                self.assertEqual(response.status_code, 302)
                post = Post.objects.get(title=fmt)
                self.assertRegex(post.cover_image.name, r"^blog/covers/[0-9a-f]{32}\.webp$")
                with Image.open(post.cover_image.path) as image:
                    self.assertEqual(image.format, "WEBP")
                    self.assertEqual(image.size, (1600, 800))
                    self.assertFalse(image.getexif())
        self.assertEqual(len(list(Path(self.media.name).rglob("*.webp"))), 3)

    def test_invalid_oversized_unsupported_and_extreme_images_are_rejected(self):
        self.client.force_login(self.admin)
        uploads = [
            SimpleUploadedFile("fake.jpg", b"<script>not an image</script>", content_type="image/jpeg"),
            SimpleUploadedFile("huge.png", b"x" * (MAX_IMAGE_BYTES + 1)),
            image_upload("GIF", name="looks-like.jpg"),
            image_upload("PNG", size=(6001, 1)),
        ]
        for upload in uploads:
            with self.subTest(name=upload.name, size=upload.size):
                response = self.client.post(self.create_url, self.data(cover_image=upload))
                self.assertEqual(response.status_code, 200)
                self.assertIn("cover_image", response.context["form"].errors)
        self.assertEqual(Post.objects.count(), 2)
        self.assertEqual(list(Path(self.media.name).rglob("*.webp")), [])

    def test_decompression_bomb_header_is_rejected_without_decoding_pixels(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")
        self.client.force_login(self.admin)
        response = self.client.post(self.create_url, self.data(cover_image=SimpleUploadedFile("bomb.png", raw)))
        self.assertIn("cover_image", response.context["form"].errors)

    def test_cover_clear_and_content_edit_keep_storage_safe(self):
        self.client.force_login(self.admin)
        self.client.post(self.edit_url, self.data(cover_image=image_upload()))
        self.draft.refresh_from_db()
        original_name = self.draft.cover_image.name
        self.client.post(self.edit_url, self.data(title="Changed text"))
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.cover_image.name, original_name)
        self.client.post(self.edit_url, self.data(**{"cover_image-clear": "on"}))
        self.draft.refresh_from_db()
        self.assertFalse(self.draft.cover_image)

    def test_empty_states(self):
        Post.objects.all().delete()
        self.assertContains(self.client.get(self.list_url), "Henüz yayınlanmış bir yazı bulunmuyor.")
        self.assertNotContains(self.client.get("/"), "Blogdan Son Yazılar")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.admin_list), "Henüz blog yazısı yok.")

    def test_queries_are_bounded_without_company_category_n_plus_one(self):
        def measure(url):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(queries)
        before = {url: measure(url) for url in ["/", self.list_url]}
        for index in range(12):
            category = CompanyCategory.objects.create(name=f"Category {index}")
            company = Company.objects.create(name=f"Company {index}", category=category)
            Complaint.objects.create(user=self.reader, company=company, title=f"Complaint {index}", description="Body", status="PUBLISHED")
            Post.objects.create(title=f"Performance post {index}", excerpt="Summary", content="Body", status="PUBLISHED", published_at=timezone.now())
        after = {url: measure(url) for url in ["/", self.list_url]}
        self.assertEqual(before, after)
        self.assertLessEqual(after["/"], 6)
        self.assertLessEqual(after[self.list_url], 2)

    def test_logout_blocks_blog_admin_and_publish_and_missing_post_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("adminx:blog_edit", args=[999999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("adminx:blog_publish", args=[999999])).status_code, 404)
        old_session = self.client.cookies["sessionid"].value
        self.client.post(reverse("accounts:logout"))
        self.client.cookies["sessionid"] = old_session
        for url in [self.admin_list, self.create_url, self.edit_url]:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(self.publish_url).status_code, 302)

from pathlib import Path

path = Path("accounts/tests.py")
text = path.read_text(encoding="utf-8")

old1 = '''    def test_profile_edit_updates_allowed_fields(self):
        user = self.create_user("editable", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Updated",
                "last_name": "Person",
                "email": "updated@example.com",
                "phone": "5559876543",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.last_name, "Person")
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.phone, "5559876543")
'''

new1 = '''    def test_profile_edit_updates_allowed_fields(self):
        user = self.create_user("editable", User.UserType.USER)
        original_email = user.email
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Updated",
                "last_name": "Person",
                # AŞAMA 4: E-posta artık profil formundan değiştirilemez.
                # İstemci elle email alanı gönderse bile yok sayılmalıdır.
                "email": "updated@example.com",
                "phone": "5559876543",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.last_name, "Person")
        self.assertEqual(user.email, original_email)
        self.assertEqual(user.phone, "5559876543")
'''

old2 = '''    def test_profile_edit_does_not_modify_another_user(self):
        user_a = self.create_user("user-a", User.UserType.USER)
        user_b = self.create_user("user-b", User.UserType.USER)
        self.client.force_login(user_a)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "id": user_b.pk,
                "user_id": user_b.pk,
                "first_name": "Changed A",
                "last_name": "Only A",
                "email": "user-a-new@example.com",
                "phone": "5554443322",
            },
        )

        self.assertEqual(response.status_code, 302)
        user_a.refresh_from_db()
        user_b.refresh_from_db()
        self.assertEqual(user_a.email, "user-a-new@example.com")
        self.assertEqual(user_b.email, "user-b@example.com")
        self.assertEqual(user_b.first_name, "")
        self.assertEqual(user_b.phone, "")
'''

new2 = '''    def test_profile_edit_does_not_modify_another_user(self):
        user_a = self.create_user("user-a", User.UserType.USER)
        user_b = self.create_user("user-b", User.UserType.USER)
        original_a_email = user_a.email
        self.client.force_login(user_a)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "id": user_b.pk,
                "user_id": user_b.pk,
                "first_name": "Changed A",
                "last_name": "Only A",
                # AŞAMA 4: Profil düzenleme endpoint'i email değiştiremez.
                "email": "user-a-new@example.com",
                "phone": "5554443322",
            },
        )

        self.assertEqual(response.status_code, 302)
        user_a.refresh_from_db()
        user_b.refresh_from_db()

        self.assertEqual(user_a.first_name, "Changed A")
        self.assertEqual(user_a.last_name, "Only A")
        self.assertEqual(user_a.phone, "5554443322")
        self.assertEqual(user_a.email, original_a_email)

        self.assertEqual(user_b.email, "user-b@example.com")
        self.assertEqual(user_b.first_name, "")
        self.assertEqual(user_b.phone, "")
'''

old3 = '''    def test_profile_edit_duplicate_email_returns_form_error(self):
        user = self.create_user("duplicate-editor", User.UserType.USER)
        other = self.create_user("duplicate-owner", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Duplicate",
                "last_name": "Email",
                "email": other.email,
                "phone": "5553332211",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        user.refresh_from_db()
        self.assertEqual(user.email, "duplicate-editor@example.com")
'''

new3 = '''    def test_profile_edit_ignores_email_field_even_if_duplicate(self):
        user = self.create_user("duplicate-editor", User.UserType.USER)
        other = self.create_user("duplicate-owner", User.UserType.USER)
        original_email = user.email
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Duplicate",
                "last_name": "Email",
                # E-posta artık bu formun alanı değildir.
                "email": other.email,
                "phone": "5553332211",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()

        self.assertEqual(user.email, original_email)
        self.assertEqual(user.first_name, "Duplicate")
        self.assertEqual(user.last_name, "Email")
        self.assertEqual(user.phone, "5553332211")

        form_page = self.client.get(reverse("accounts:profile_edit"))
        self.assertNotIn("email", form_page.context["form"].fields)
'''

replacements = [(old1, new1), (old2, new2), (old3, new3)]

for i, (old, new) in enumerate(replacements, start=1):
    if old not in text:
        raise SystemExit(
            f"Beklenen test bloğu {i} bulunamadı. Dosya değişmiş olabilir; hiçbir değişiklik yapılmadı."
        )

backup = path.with_suffix(".py.stage4_backup")
backup.write_text(text, encoding="utf-8")

for old, new in replacements:
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

print("OK: accounts/tests.py güncellendi.")
print(f"Yedek: {backup}")
print("Şimdi çalıştır:")
print("python manage.py test accounts")

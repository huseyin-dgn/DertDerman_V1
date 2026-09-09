# Dosya bazında diff incelemesi

8 Eylül 2026. Önceki değişiklikler korunarak incelendi.

| Dosya | Değişiklik nedeni |
|---|---|
| `adminx/blog_views.py` | Admin blog arama/filtre, 5 kayıt, yazar atama, arşiv dışlama ve POST silme endpointi. |
| `adminx/content_views.py` | Admin şirket/başvuru/kullanıcı listeleri, güvenli içerik düzenleme ve POST şirket arşivleme. |
| `adminx/context_processors.py` | Admin sidebar aktif bölüm ve breadcrumb bağlamı. |
| `adminx/filters.py` | Doğrulanan arama/durum/kategori/rol filtreleri ve ortak sayfalama. |
| `adminx/services.py` | Transaction içinde fiziksel silme yapmadan blog/company arşivleme; tekrarlı istekte idempotency. |
| `adminx/test_archiving.py` | Admin davranış/rol/CSRF/sayfalama regresyon testleri; arşiv testlerinde ilişki ve erişim koruması. |
| `adminx/test_content.py` | Admin davranış/rol/CSRF/sayfalama regresyon testleri; arşiv testlerinde ilişki ve erişim koruması. |
| `adminx/test_v2.py` | Admin davranış/rol/CSRF/sayfalama regresyon testleri; arşiv testlerinde ilişki ve erişim koruması. |
| `adminx/tests.py` | Admin davranış/rol/CSRF/sayfalama regresyon testleri; arşiv testlerinde ilişki ve erişim koruması. |
| `adminx/urls.py` | Arşiv/silme ile önceki admin detay ve olay ekranlarını view fonksiyonlarına bağlama. |
| `adminx/views.py` | Gerçek dashboard verileri, filtreli moderasyon ve olay listeleri; bu tur admin aktivite de 5 kayıt. |
| `blog/migrations/0002_post_author.py` | Eski kayıtlara nullable author alanı migrationı (önceden uygulanmıştı). |
| `blog/migrations/0003_alter_post_status.py` | ARCHIVED choice migrationı; bu tur uygulandı. |
| `blog/models.py` | Nullable author ilişkisi ve ARCHIVED status choice. |
| `blog/tests.py` | Public/panel sayfalama, görünürlük, XSS, reader veya ortak querystring davranışını doğrulayan testler. |
| `blog/views.py` | 6 kayıt, arama, ortak direct/fragment reader ve Vary header. |
| `companies/forms.py` | Bu tur login sorgusu ortak erişim helperına bağlandı; arşiv markerı atlanamaz. |
| `companies/migrations/0004_company_archived_at.py` | archived_at alanı migrationı; bu tur uygulandı. |
| `companies/models.py` | Soft archive için nullable archived_at. |
| `companies/panel_selectors.py` | Önceki hareket geçmişini SQL UNION ile tam ve sıralı sayfalama. |
| `companies/panel_views.py` | Önceki ortak pagination ve sınırlı dashboard/list/detail bağlantıları. |
| `companies/selectors.py` | Public şirketlerde APPROVED + active + arşivlenmemiş koşulları ve kesin ordering. |
| `companies/services.py` | Arşivli şirket başvurusunu engelleme; bu tur aktif üyelik sorgusunda archived_at kontrolü. |
| `companies/test_panel.py` | Public/panel sayfalama, görünürlük, XSS, reader veya ortak querystring davranışını doğrulayan testler. |
| `companies/views.py` | 8 kayıt, server-side arama, published şikayet sayısı ve public detay görünürlük filtresi. |
| `complaints/tests.py` | Public/panel sayfalama, görünürlük, XSS, reader veya ortak querystring davranışını doğrulayan testler. |
| `complaints/views.py` | Önceki ortak public/user/response sayfalaması. |
| `config/settings.py` | Admin navigation context processor kaydı. |
| `core/pagination.py` | Merkezi sayfa boyutları ve invalid page için Paginator.get_page. |
| `core/templatetags/__init__.py` | Django template tag paket kaydı. |
| `core/templatetags/pagination_tags.py` | Querystring koruyan sayfa URLleri ve elided sayfa numaraları. |
| `core/test_pagination.py` | Public/panel sayfalama, görünürlük, XSS, reader veya ortak querystring davranışını doğrulayan testler. |
| `core/test_public_experience.py` | Public/panel sayfalama, görünürlük, XSS, reader veya ortak querystring davranışını doğrulayan testler. |
| `core/views.py` | Ana sayfa şirket önizlemesinde ortak public görünürlük filtresi. |
| `docs/UI_UX_V2_REPORT.md` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-files.txt` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/confirmation-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/dashboard-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/drawer-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/empty-state-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/results.json` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sikayetler-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/sirket-basvurulari-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/admin-v2-qa/test-results.txt` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/full-suite-current.txt` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/blog-confirm-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/company-confirm-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/directory-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/journal-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-1024.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-1366.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-1440.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-430.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/reader-768.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/results.json` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `media/blog/covers/71fcf19cc0e541b28b94411bfc087cf9.webp` | Önceki blog kapak görseli; korundu, yeniden üretilmedi. |
| `scripts/qa_admin_v2.py` | Önceki admin QA scripti; korundu. |
| `scripts/qa_public_archive.py` | Bu tur geçici DB ile altı viewport, modal, fallback ve arşiv confirmation QA. |
| `static/css/admin-panel.css` | Önceki admin layout, responsive tablo/drawer, badge ve confirmation stilleri. |
| `static/css/discovery.css` | Şirket/blog kartları ve okuyucu stilleri; bu tur mobil reader gerçek tam ekran. |
| `static/css/pagination.css` | Ortak responsive pagination stilleri. |
| `static/js/admin-panel.js` | Önceki drawer/feedback ve CSRF formunu orijinal submitter ile gönderen confirmation UI. |
| `static/js/article-reader.js` | Fetch, ESC/backdrop/close, history ve scroll lock; bu tur focus döngüsü ve history scroll sırası düzeltildi. |
| `templates/accounts/password_change.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/accounts/profile.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/accounts/profile_edit.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/adminx/blog_delete_action.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/blog_form.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/blog_list.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/company_application_detail.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/company_application_list.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/company_archive_action.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/company_form.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/company_list.html` | Admin şirket tablosu, arşiv durumu rozeti ve POST/CSRF arşiv onay formu. |
| `templates/adminx/complaint_detail.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/complaint_list.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/content_base.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/content_pagination.html` | Ortak querystring koruyan pagination şablonuna bağlantı. |
| `templates/adminx/event_list.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/filters.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/home.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/homepage_content.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/kpi.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/table_base.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/user_detail.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/adminx/user_list.html` | Önceki admin tablo/form/dashboard/confirmation bileşeni; mevcut view/URL/CSRF bağları incelendi. |
| `templates/base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/blog/article.html` | Public blog kart/list/detail veya paylaşılan reader HTML; normal anchor ve autoescaping korunur. |
| `templates/blog/index_card.html` | Public blog kart/list/detail veya paylaşılan reader HTML; normal anchor ve autoescaping korunur. |
| `templates/blog/post_detail.html` | Public blog kart/list/detail veya paylaşılan reader HTML; normal anchor ve autoescaping korunur. |
| `templates/blog/post_list.html` | Public blog kart/list/detail veya paylaşılan reader HTML; normal anchor ve autoescaping korunur. |
| `templates/blog/reader_dialog.html` | Public blog kart/list/detail veya paylaşılan reader HTML; normal anchor ve autoescaping korunur. |
| `templates/companies/company_list.html` | Public şirket rehberi, responsive kart, server-side arama ve pagination HTML. |
| `templates/companies/directory_card.html` | Public şirket rehberi, responsive kart, server-side arama ve pagination HTML. |
| `templates/companies/panel/base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/companies/panel/complaint_detail.html` | Önceki panel/public şablonunda pagination, toplam kayıt veya sayfalı geçmiş bağlantısı. |
| `templates/companies/panel/members.html` | Önceki panel/public şablonunda pagination, toplam kayıt veya sayfalı geçmiş bağlantısı. |
| `templates/companies/panel/pagination.html` | Ortak querystring koruyan pagination şablonuna bağlantı. |
| `templates/complaints/complaint_create.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/complaints/complaint_list.html` | Önceki panel/public şablonunda pagination, toplam kayıt veya sayfalı geçmiş bağlantısı. |
| `templates/complaints/private_base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/complaints/public_detail.html` | Önceki panel/public şablonunda pagination, toplam kayıt veya sayfalı geçmiş bağlantısı. |
| `templates/complaints/public_list.html` | Önceki panel/public şablonunda pagination, toplam kayıt veya sayfalı geçmiş bağlantısı. |
| `templates/components/badge.html` | Önceki ortak badge/breadcrumb/empty state veya pagination bileşeni. |
| `templates/components/breadcrumbs.html` | Önceki ortak badge/breadcrumb/empty state veya pagination bileşeni. |
| `templates/components/empty_state.html` | Önceki ortak badge/breadcrumb/empty state veya pagination bileşeni. |
| `templates/components/pagination.html` | Ortak querystring koruyan pagination şablonuna bağlantı. |
| `templates/components/public_empty.html` | Önceki ortak badge/breadcrumb/empty state veya pagination bileşeni. |
| `templates/layouts/admin_base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/layouts/company_base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/layouts/public_base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `templates/layouts/user_base.html` | Önceki rol layout ayrımı/uyumluluk şablonu; public/company içerik taşınırken korundu. |
| `docs/PUBLIC_ARCHIVE_FILE_REVIEW.md` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/PUBLIC_ARCHIVE_COMPLETION.md` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |
| `docs/public-archive-qa/direct-nojs-375.png` | QA raporu, dosya envanteri, test çıktısı veya ekran görüntüsü; eski kanıtlar korundu, yeni kanıtlar ayrı dizinde. |

from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(__file__).resolve().parent

FILES = {
    "complaint_card": ROOT / "templates/complaints/public_card.html",
    "complaint_detail": ROOT / "templates/complaints/public_detail.html",
    "blog_index_card": ROOT / "templates/blog/index_card.html",
    "blog_card": ROOT / "templates/blog/card.html",
    "experience_css": ROOT / "static/css/experience-v2.css",
    "discovery_css": ROOT / "static/css/discovery.css",
}

def read(path):
    if not path.exists():
        raise SystemExit(f"Dosya bulunamadı: {path}")
    return path.read_text(encoding="utf-8")

def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"GÜNCELLENDİ: {path.relative_to(ROOT)}")

backup = ROOT / f"_backup_metrics_ui_{datetime.now():%Y%m%d_%H%M%S}"
backup.mkdir(parents=True, exist_ok=True)

for path in FILES.values():
    if path.exists():
        target = backup / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

complaint_card = """<article class="public-complaint-card">
  <header class="public-card-company">
    <span class="public-card-logo">
      {% include 'components/company_avatar.html' with company=complaint.company image_class='public-card-logo-image' fallback_class='public-card-logo-fallback' only %}
    </span>
    <span class="public-card-company-name">
      {{ complaint.company.name }}
      {% if complaint.company.is_verified %}
        <span class="verified-mark" title="Doğrulanmış şirket" aria-label="Doğrulanmış şirket">✓</span>
      {% endif %}
    </span>
    {% include 'complaints/status_badge.html' with complaint=complaint only %}
  </header>

  <div class="public-card-content">
    <h3 class="complaint-card-title">
      <a href="{% url 'complaints:public_detail' complaint.pk %}">{{ complaint.title }}</a>
    </h3>
    <p class="complaint-preview">{{ complaint.description|truncatechars:165 }}</p>

    <div class="public-card-badges">
      {% if complaint.has_response %}
        <span class="community-chip community-chip--response">Şirket cevapladı</span>
      {% endif %}
      {% if complaint.status == 'RESOLVED' %}
        <span class="community-chip community-chip--resolved">Sorun çözüldü</span>
      {% endif %}
    </div>
  </div>

  <footer class="public-complaint-meta public-complaint-meta--clean">
    <div class="public-card-author">
      {% include 'components/complaint_author_avatar.html' with complaint=complaint size_class='user-avatar--xs' only %}
      <span>
        DertDerman kullanıcısı ·
        <time datetime="{{ complaint.created_at|date:'c' }}">{{ complaint.created_at|date:'d.m.Y' }}</time>
      </span>
    </div>

    <div class="public-card-bottom">
      <div class="public-card-counts public-card-counts--clean" aria-label="Etkileşimler">
        <span class="metric-chip" title="Görüntülenme">
          {% include 'components/icon.html' with name='eye' %}
          <b>{{ complaint.view_count|default:0 }}</b>
        </span>
        <span class="metric-chip">
          <span class="metric-chip-label">Tepki</span>
          <b>{{ complaint.reaction_count|default:0 }}</b>
        </span>
        <span class="metric-chip">
          <span class="metric-chip-label">Yorum</span>
          <b>{{ complaint.comment_count|default:0 }}</b>
        </span>
      </div>

      <a class="detail-cta public-card-action public-card-action--compact"
         href="{% url 'complaints:public_detail' complaint.pk %}">
        İncele →
      </a>
    </div>
  </footer>
</article>
"""
write(FILES["complaint_card"], complaint_card)

detail = read(FILES["complaint_detail"])
old = """    <div class="interaction-summary" aria-label="Şikayet istatistikleri">
      <span>
        {% include 'components/icon.html' with name='eye' %}
        <b>{{ complaint.view_count|default:0 }}</b>
        görüntülenme
      </span>

      <span>
        <b>{{ complaint.comment_count|default:0 }}</b>
        yorum
      </span>
    </div>"""
new = """    <div class="interaction-summary interaction-summary--clean" aria-label="Şikayet istatistikleri">
      <span class="interaction-stat">
        {% include 'components/icon.html' with name='eye' %}
        <b>{{ complaint.view_count|default:0 }}</b>
        <small>görüntülenme</small>
      </span>

      <span class="interaction-stat">
        <b>{{ complaint.comment_count|default:0 }}</b>
        <small>yorum</small>
      </span>
    </div>"""
if old in detail:
    detail = detail.replace(old, new, 1)
write(FILES["complaint_detail"], detail)

blog_index = """<article class="journal-card">
  <a class="journal-card-image"
     href="{% url 'blog:detail' post.slug %}"
     data-article-link
     aria-label="{{ post.title }} yazısını oku">
    {% if post.cover_image %}
      <img src="{{ post.cover_image.url }}" alt="" width="640" height="400" loading="lazy" decoding="async">
    {% else %}
      <div class="journal-cover-fallback" aria-hidden="true">
        <span class="journal-cover-label">DERTDERMAN / BLOG</span>
        <span class="journal-cover-mark">{% include 'components/icon.html' with name='write' %}</span>
        <span class="journal-cover-line"></span>
      </div>
    {% endif %}

    <span class="journal-view-badge" title="Görüntülenme">
      {% include 'components/icon.html' with name='eye' %}
      {{ post.view_count|default:0 }}
    </span>

    <span class="journal-image-action" aria-hidden="true">
      {% include 'components/icon.html' %}
    </span>
  </a>

  <div class="journal-card-body">
    <p class="journal-card-meta">
      <span>DERTDERMAN</span>
      <time datetime="{{ post.published_at|date:'c' }}">{{ post.published_at|date:'d F Y' }}</time>
    </p>

    <h2>
      <a href="{% url 'blog:detail' post.slug %}" data-article-link>{{ post.title }}</a>
    </h2>

    <p class="journal-excerpt">{{ post.excerpt }}</p>

    <a class="detail-cta journal-read-link"
       href="{% url 'blog:detail' post.slug %}"
       data-article-link>
      Yazıyı Oku →
    </a>
  </div>
</article>
"""
write(FILES["blog_index_card"], blog_index)

blog_card = """<article class="blog-card">
    <div class="blog-cover-wrap">
        {% if post.cover_image %}
            <img class="blog-cover"
                 src="{{ post.cover_image.url }}"
                 alt="{{ post.title }}"
                 width="640"
                 height="360"
                 loading="lazy"
                 decoding="async">
        {% else %}
            <div class="blog-placeholder" aria-hidden="true">
                <span>Dert<span class="blog-connection"></span>Derman</span>
            </div>
        {% endif %}

        <span class="blog-cover-view-badge" title="Görüntülenme">
            {% include 'components/icon.html' with name='eye' %}
            {{ post.view_count|default:0 }}
        </span>
    </div>

    <div class="blog-card-body">
        <time datetime="{{ post.published_at|date:'c' }}">{{ post.published_at|date:'d.m.Y' }}</time>
        <h2><a href="{% url 'blog:detail' post.slug %}">{{ post.title }}</a></h2>
        <p>{{ post.excerpt }}</p>
        <a class="detail-cta" href="{% url 'blog:detail' post.slug %}">Yazıyı Oku →</a>
    </div>
</article>
"""
write(FILES["blog_card"], blog_card)

css = read(FILES["experience_css"])
marker = "/* Metrics UI cleanup */"
if marker not in css:
    css += """

/* Metrics UI cleanup */
.public-complaint-meta--clean {
  display: grid !important;
  grid-template-columns: 1fr !important;
  gap: 12px !important;
  align-items: stretch !important;
}

.public-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.public-card-counts--clean {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.metric-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 5px 9px;
  border: 1px solid #dbe7f0;
  border-radius: 999px;
  background: #f8fbfd;
  color: #60788d;
  font-size: .64rem;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}

.metric-chip .icon {
  width: 14px;
  height: 14px;
  color: #4d7697;
}

.metric-chip b {
  color: #244b69;
  font-size: .67rem;
  font-variant-numeric: tabular-nums;
}

.metric-chip-label {
  color: #6d8295;
}

.public-card-action--compact {
  min-width: 104px;
  min-height: 34px;
  padding: 7px 12px;
  box-shadow: none;
}

.interaction-summary--clean {
  display: flex;
  gap: 8px;
}

.interaction-stat {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid #d9e5ee;
  border-radius: 999px;
  background: #fff;
  color: #5f768a;
}

.interaction-stat .icon {
  width: 15px;
  height: 15px;
  color: #4f7898;
}

.interaction-stat b {
  color: #244b69;
  font-size: .72rem;
}

.interaction-stat small {
  font-size: .62rem;
  color: #7890a3;
}

@media (max-width: 600px) {
  .public-card-bottom {
    align-items: stretch;
    flex-direction: column;
  }

  .public-card-counts--clean {
    flex-wrap: wrap;
  }

  .public-card-action--compact {
    width: 100%;
  }
}
"""
write(FILES["experience_css"], css)

dcss = read(FILES["discovery_css"])
marker = "/* Blog view-count visual cleanup */"
if marker not in dcss:
    dcss += """

/* Blog view-count visual cleanup */
.journal-card-image,
.blog-cover-wrap {
  position: relative;
}

.journal-view-badge,
.blog-cover-view-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgb(15 39 60 / 78%);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  backdrop-filter: blur(6px);
  box-shadow: 0 5px 14px rgb(11 32 49 / 18%);
}

.journal-view-badge {
  position: absolute;
  left: 14px;
  bottom: 14px;
  z-index: 2;
}

.blog-cover-view-badge {
  position: absolute;
  right: 12px;
  bottom: 12px;
  z-index: 2;
}

.journal-view-badge .icon,
.blog-cover-view-badge .icon {
  width: 15px;
  height: 15px;
  color: currentColor;
}

.journal-card-meta {
  justify-content: space-between;
}

.reader-view-count {
  padding: 5px 9px;
  border: 1px solid #dbe5ed;
  border-radius: 999px;
  background: #f8fbfd;
}

.reader-view-count b {
  font-size: 12px;
}
"""
write(FILES["discovery_css"], dcss)

print()
print("TAMAMLANDI")
print(f"Yedek klasörü: {backup.name}")
print("Şimdi çalıştır:")
print("python manage.py check")
print("python manage.py test complaints.test_public_social blog")
print("python manage.py runserver")

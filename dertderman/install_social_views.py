from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent

paths = {
    "complaint_models": ROOT / "complaints/models.py",
    "blog_models": ROOT / "blog/models.py",
    "view_tracking": ROOT / "core/view_tracking.py",
    "complaint_views": ROOT / "complaints/views.py",
    "blog_views": ROOT / "blog/views.py",
    "complaint_detail": ROOT / "templates/complaints/public_detail.html",
    "complaint_card": ROOT / "templates/complaints/public_card.html",
    "blog_article": ROOT / "templates/blog/article.html",
    "blog_index_card": ROOT / "templates/blog/index_card.html",
    "blog_card": ROOT / "templates/blog/card.html",
    "icon": ROOT / "templates/components/icon.html",
    "experience_css": ROOT / "static/css/experience-v2.css",
    "social_tests": ROOT / "complaints/test_public_social.py",
}


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Dosya bulunamadı: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"GÜNCELLENDİ: {path.relative_to(ROOT)}")


backup_root = ROOT / f"_backup_social_views_{datetime.now():%Y%m%d_%H%M%S}"

for path in paths.values():
    if path.exists():
        target = backup_root / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


# Complaint görüntülenme sayacı
text = read(paths["complaint_models"])

if "view_count = models.PositiveBigIntegerField(" not in text:
    old = '''    updated_at = models.DateTimeField(
        auto_now=True,
    )

    withdrawn_at = models.DateTimeField(
'''

    new = '''    updated_at = models.DateTimeField(
        auto_now=True,
    )

    view_count = models.PositiveBigIntegerField(
        default=0,
        editable=False,
    )

    withdrawn_at = models.DateTimeField(
'''

    if old not in text:
        raise SystemExit("Complaint.updated_at bloğu bulunamadı.")

    text = text.replace(old, new, 1)

write(paths["complaint_models"], text)


# Blog görüntülenme sayacı
text = read(paths["blog_models"])

if "view_count = models.PositiveBigIntegerField(" not in text:
    old = (
        "    updated_at = models.DateTimeField(auto_now=True)\n"
        "    published_at = models.DateTimeField(null=True, blank=True, editable=False)\n"
    )

    new = (
        "    updated_at = models.DateTimeField(auto_now=True)\n"
        "    view_count = models.PositiveBigIntegerField(default=0, editable=False)\n"
        "    published_at = models.DateTimeField(null=True, blank=True, editable=False)\n"
    )

    if old not in text:
        raise SystemExit("Post.updated_at bloğu bulunamadı.")

    text = text.replace(old, new, 1)

write(paths["blog_models"], text)


# Ortak görüntülenme servisi
write(
    paths["view_tracking"],
    '''from __future__ import annotations

from django.db.models import F


MAX_TRACKED_OBJECTS_PER_TYPE = 500


def record_unique_session_view(
    request,
    *,
    instance,
    namespace: str,
) -> int:
    if request.method != "GET":
        return int(
            getattr(
                instance,
                "view_count",
                0,
            )
            or 0
        )

    session_key = f"_dd_viewed_{namespace}"

    viewed = list(
        request.session.get(
            session_key,
            [],
        )
    )

    object_key = str(instance.pk)

    if object_key in viewed:
        return int(instance.view_count or 0)

    instance.__class__.objects.filter(
        pk=instance.pk
    ).update(
        view_count=F("view_count") + 1
    )

    instance.view_count = (
        int(instance.view_count or 0)
        + 1
    )

    viewed.append(object_key)

    request.session[session_key] = viewed[
        -MAX_TRACKED_OBJECTS_PER_TYPE:
    ]

    request.session.modified = True

    return int(instance.view_count)
'''
)


# complaints/views.py
text = read(paths["complaint_views"])

marker = "from core.decorators import role_required\n"

if "from core.view_tracking import record_unique_session_view\n" not in text:
    if marker not in text:
        raise SystemExit(
            "complaints/views.py import noktası bulunamadı."
        )

    text = text.replace(
        marker,
        marker
        + "from core.view_tracking import record_unique_session_view\n",
        1,
    )


old = '''    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    return render(
'''

new = '''    complaint = get_object_or_404(
        public_complaints(),
        pk=pk
    )

    complaint.view_count = record_unique_session_view(
        request,
        instance=complaint,
        namespace="complaint",
    )

    return render(
'''

if 'namespace="complaint"' not in text:
    if old not in text:
        raise SystemExit(
            "public_complaint_detail bloğu bulunamadı."
        )

    text = text.replace(old, new, 1)


old = '''        if (
            current
            and current.reaction_type == reaction_type
        ):
            current.delete()
            created = False
'''

new = '''        if (
            current
            and current.reaction_type == reaction_type
        ):
            # Aynı emojiye tekrar basmak tepkiyi kaldırmaz.
            created = False
'''

if old in text:
    text = text.replace(old, new, 1)

elif "# Aynı emojiye tekrar basmak tepkiyi kaldırmaz." not in text:
    raise SystemExit(
        "complaint_react aynı emoji bloğu bulunamadı."
    )

write(paths["complaint_views"], text)


# blog/views.py
write(
    paths["blog_views"],
    '''from core.pagination import paginate
from core.view_tracking import record_unique_session_view
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_headers

from .selectors import published_posts


@require_safe
def post_list(request):
    search = request.GET.get(
        "s",
        request.GET.get("q", "")
    ).strip()[:180]

    posts = published_posts().defer("content")

    if search:
        posts = posts.filter(
            Q(title__icontains=search)
            | Q(excerpt__icontains=search)
        )

    page_obj = paginate(
        request,
        posts,
        "public_blog",
    )

    return render(
        request,
        "blog/post_list.html",
        {
            "page_obj": page_obj,
            "search": search,
        },
    )


@require_safe
@vary_on_headers("X-Article-Reader")
def post_detail(request, slug):
    post = get_object_or_404(
        published_posts(),
        slug=slug,
    )

    post.view_count = record_unique_session_view(
        request,
        instance=post,
        namespace="blog_post",
    )

    template = (
        "blog/article.html"
        if request.headers.get(
            "X-Article-Reader"
        ) == "1"
        else "blog/post_detail.html"
    )

    response = render(
        request,
        template,
        {
            "post": post,
        },
    )

    response["Cache-Control"] = "no-cache"

    return response
'''
)


# Şikayet interaction panel
text = read(paths["complaint_detail"])

start = text.find(
    '<section class="interaction-panel"'
)

end = text.find(
    '<section class="official-response-section"'
)

if start == -1 or end == -1 or end <= start:
    raise SystemExit(
        "Şikayet etkileşim paneli bulunamadı."
    )


panel = '''<section class="interaction-panel" aria-labelledby="interaction-title">
  <header>
    <div>
      <p class="section-kicker">TOPLULUK DESTEĞİ</p>
      <h2 id="interaction-title">Bu deneyim size de tanıdık geliyor mu?</h2>
    </div>

    <div class="interaction-summary" aria-label="Şikayet istatistikleri">
      <span>
        {% include 'components/icon.html' with name='eye' %}
        <b>{{ complaint.view_count|default:0 }}</b>
        görüntülenme
      </span>

      <span>
        <b>{{ complaint.comment_count|default:0 }}</b>
        yorum
      </span>
    </div>
  </header>

  <div class="interaction-bar">
    {% if request.user.is_authenticated and request.user.user_type == 'USER' %}

      <form
        class="emoji-picker emoji-picker--direct"
        method="post"
        action="{% url 'complaints:react' complaint.pk %}"
      >
        {% csrf_token %}

        <div
          class="emoji-options"
          aria-label="Emoji tepkileri"
        >
          {% for reaction in reaction_options %}

            <button
              type="submit"
              name="reaction_type"
              value="{{ reaction.value }}"
              class="emoji-option{% if reaction.active %} is-active{% endif %}"
              aria-pressed="{% if reaction.active %}true{% else %}false{% endif %}"
              title="{{ reaction.count }} tepki"
            >
              <span aria-hidden="true">
                {{ reaction.value }}
              </span>

              <b>{{ reaction.count }}</b>
            </button>

          {% endfor %}
        </div>
      </form>

      {% if request.user.pk != complaint.user_id %}
        <button
          type="button"
          class="report-trigger"
          data-report-open="complaint-report-dialog"
        >
          ⚑ Raporla
        </button>
      {% endif %}

    {% else %}

      <a
        class="secondary-action"
        href="{% url 'accounts:login' %}?next={{ request.path|urlencode }}"
      >
        Tepki vermek için giriş yapın
      </a>

    {% endif %}

    <a
      class="comment-count-link"
      href="#community-comments"
    >
      💬 {{ complaint.comment_count }} Yorum
    </a>
  </div>
</section>
'''

text = (
    text[:start]
    + panel
    + "\n"
    + text[end:]
)

write(
    paths["complaint_detail"],
    text,
)


# Şikayet kartı
write(
    paths["complaint_card"],
    '''<article class="public-complaint-card"><header class="public-card-company"><span class="public-card-logo">{% include 'components/company_avatar.html' with company=complaint.company image_class='public-card-logo-image' fallback_class='public-card-logo-fallback' only %}</span><span class="public-card-company-name">{{ complaint.company.name }}{% if complaint.company.is_verified %}<span class="verified-mark" title="Doğrulanmış şirket" aria-label="Doğrulanmış şirket">✓</span>{% endif %}</span>{% include 'complaints/status_badge.html' with complaint=complaint only %}</header><div class="public-card-content"><h3 class="complaint-card-title"><a href="{% url 'complaints:public_detail' complaint.pk %}">{{ complaint.title }}</a></h3><p class="complaint-preview">{{ complaint.description|truncatechars:165 }}</p><div class="public-card-badges">{% if complaint.has_response %}<span class="community-chip community-chip--response">Şirket cevapladı</span>{% endif %}{% if complaint.status == 'RESOLVED' %}<span class="community-chip community-chip--resolved">Sorun çözüldü</span>{% endif %}</div></div><footer class="public-complaint-meta"><span class="public-card-author">{% include 'components/complaint_author_avatar.html' with complaint=complaint size_class='user-avatar--xs' only %}<span>DertDerman kullanıcısı · <time datetime="{{ complaint.created_at|date:'c' }}">{{ complaint.created_at|date:'d.m.Y' }}</time></span></span><span class="public-card-counts" aria-label="Etkileşimler"><span title="Görüntülenme">{% include 'components/icon.html' with name='eye' %} {{ complaint.view_count|default:0 }}</span><span>Tepki {{ complaint.reaction_count|default:0 }}</span><span>Yorum {{ complaint.comment_count|default:0 }}</span></span><a class="detail-cta public-card-action" href="{% url 'complaints:public_detail' complaint.pk %}">İncele →</a></footer></article>
'''
)


# Blog article
write(
    paths["blog_article"],
    '''<article class="reader-article" data-reader-article aria-labelledby="reader-title">
  <header class="reader-article-heading">
    <p class="discovery-eyebrow">DERTDERMAN / BLOG &amp; REHBER</p>
    <h1 id="reader-title" tabindex="-1">{{ post.title }}</h1>
    <p class="reader-lead">{{ post.excerpt }}</p>

    <div class="reader-meta">
      <span>
        {% include 'companies/panel/icon.html' with name='calendar' %}
        <time datetime="{{ post.published_at|date:'c' }}">
          {{ post.published_at|date:'d F Y' }}
        </time>
      </span>

      <span>DertDerman Blog</span>

      <span class="reader-view-count">
        {% include 'components/icon.html' with name='eye' %}
        <b>{{ post.view_count|default:0 }}</b>
        görüntülenme
      </span>
    </div>
  </header>

  {% if post.cover_image %}
    <figure class="reader-cover">
      <img
        src="{{ post.cover_image.url }}"
        alt="{{ post.title }}"
        width="1200"
        height="675"
        decoding="async"
      >
    </figure>
  {% endif %}

  <div class="reader-prose">
    {{ post.content|linebreaks }}
  </div>

  <footer class="reader-article-footer">
    <span>Bilgiyle bir adım ileri.</span>
    <a href="{% url 'blog:list' %}" data-reader-return>
      Tüm Yazılara Dön
      {% include 'components/icon.html' %}
    </a>
  </footer>
</article>
'''
)


# Blog index card
write(
    paths["blog_index_card"],
    '''<article class="journal-card">
  <a
    class="journal-card-image"
    href="{% url 'blog:detail' post.slug %}"
    data-article-link
    aria-label="{{ post.title }} yazısını oku"
  >
    {% if post.cover_image %}
      <img
        src="{{ post.cover_image.url }}"
        alt=""
        width="640"
        height="400"
        loading="lazy"
        decoding="async"
      >
    {% else %}
      <div class="journal-cover-fallback" aria-hidden="true">
        <span class="journal-cover-label">DERTDERMAN / BLOG</span>
        <span class="journal-cover-mark">
          {% include 'components/icon.html' with name='write' %}
        </span>
        <span class="journal-cover-line"></span>
      </div>
    {% endif %}

    <span class="journal-image-action" aria-hidden="true">
      {% include 'components/icon.html' %}
    </span>
  </a>

  <div class="journal-card-body">
    <p class="journal-card-meta">
      <span>DERTDERMAN</span>

      <span
        class="journal-card-views"
        title="Görüntülenme"
      >
        {% include 'components/icon.html' with name='eye' %}
        {{ post.view_count|default:0 }}
      </span>

      <time datetime="{{ post.published_at|date:'c' }}">
        {{ post.published_at|date:'d F Y' }}
      </time>
    </p>

    <h2>
      <a
        href="{% url 'blog:detail' post.slug %}"
        data-article-link
      >
        {{ post.title }}
      </a>
    </h2>

    <p class="journal-excerpt">
      {{ post.excerpt }}
    </p>

    <a
      class="detail-cta journal-read-link"
      href="{% url 'blog:detail' post.slug %}"
      data-article-link
    >
      Yazıyı Oku →
    </a>
  </div>
</article>
'''
)


# Ana sayfa blog kartı
write(
    paths["blog_card"],
    '''<article class="blog-card">
    {% if post.cover_image %}
        <img
            class="blog-cover"
            src="{{ post.cover_image.url }}"
            alt="{{ post.title }}"
            width="640"
            height="360"
            loading="lazy"
            decoding="async"
        >
    {% else %}
        <div class="blog-placeholder" aria-hidden="true">
            <span>
                Dert
                <span class="blog-connection"></span>
                Derman
            </span>
        </div>
    {% endif %}

    <div class="blog-card-body">

        <div class="blog-card-meta-row">
            <time datetime="{{ post.published_at|date:'c' }}">
                {{ post.published_at|date:'d.m.Y' }}
            </time>

            <span
                class="content-view-count"
                title="Görüntülenme"
            >
                {% include 'components/icon.html' with name='eye' %}
                {{ post.view_count|default:0 }}
            </span>
        </div>

        <h2>
            <a href="{% url 'blog:detail' post.slug %}">
                {{ post.title }}
            </a>
        </h2>

        <p>{{ post.excerpt }}</p>

        <a
            class="detail-cta"
            href="{% url 'blog:detail' post.slug %}"
        >
            Yazıyı Oku →
        </a>
    </div>
</article>
'''
)


# Eye icon
text = read(paths["icon"])

if "name == 'eye'" not in text:
    old = (
        '{% else %}'
        '<path d="M3 12h18m-7-7 7 7-7 7"/>'
    )

    new = (
        "{% elif name == 'eye' %}"
        '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/>'
        '<circle cx="12" cy="12" r="2.75"/>'
        + old
    )

    if old not in text:
        raise SystemExit(
            "components/icon.html varsayılan ikon bloğu bulunamadı."
        )

    text = text.replace(
        old,
        new,
        1,
    )

write(paths["icon"], text)


# CSS
text = read(paths["experience_css"])

marker = (
    "/* Direct emoji reactions + content view counters */"
)

if marker not in text:
    text = text.rstrip() + '''

/* Direct emoji reactions + content view counters */

.emoji-picker--direct {
  flex: 1 1 100%;
  padding: 9px;
}

.emoji-picker--direct .emoji-options {
  display: flex;
  width: 100%;
  gap: 7px;
  overflow-x: auto;
  scrollbar-width: thin;
}

.emoji-picker--direct .emoji-option {
  position: relative;
  display: inline-flex;
  min-width: 52px;
  height: 42px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid #d7e4ee;
  border-radius: 10px;
  background: #f7fbfe;
  color: var(--text);
  font-size: 1.08rem;
  transition:
    transform .14s,
    border-color .14s,
    background-color .14s,
    box-shadow .14s;
}

.emoji-picker--direct .emoji-option:hover {
  border-color: #8bb8d8;
  background: #edf7fd;
  transform: translateY(-1px);
}

.emoji-picker--direct .emoji-option.is-active {
  border-color: var(--primary);
  background: #e7f3fc;
  box-shadow:
    inset 0 0 0 1px var(--primary),
    0 6px 16px rgb(29 95 167 / 10%);
}

.emoji-picker--direct .emoji-option b {
  position: static;
  min-width: 14px;
  color: var(--primary);
  font-size: .68rem;
  font-variant-numeric: tabular-nums;
}

.interaction-summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 14px;
  color: var(--text-muted);
  font-size: .72rem;
}

.interaction-summary > span,
.public-card-counts > span,
.content-view-count,
.journal-card-views,
.reader-view-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.interaction-summary .icon,
.public-card-counts .icon,
.content-view-count .icon,
.journal-card-views .icon,
.reader-view-count .icon {
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
}

.interaction-summary b,
.reader-view-count b {
  color: var(--dd-navy);
  font-variant-numeric: tabular-nums;
}

.public-card-counts {
  align-items: center;
}

.public-card-counts > span {
  white-space: nowrap;
}

.blog-card-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--dd-muted);
  font-size: .75rem;
}

.content-view-count,
.journal-card-views,
.reader-view-count {
  font-variant-numeric: tabular-nums;
}

.content-view-count {
  color: var(--dd-muted);
  font-size: .72rem;
  font-weight: 700;
}

.journal-card-meta {
  flex-wrap: wrap;
}

.journal-card-views {
  color: #657f95;
  font-size: 10px;
  font-weight: 700;
}

@media (max-width: 700px) {
  .interaction-panel > header {
    align-items: flex-start;
  }

  .interaction-summary {
    justify-content: flex-start;
  }

  .emoji-picker--direct {
    align-items: stretch;
  }

  .emoji-picker--direct .emoji-options {
    width: 100%;
  }
}
'''

write(
    paths["experience_css"],
    text,
)


# Testi yeni reaction davranışına uyarla
text = read(paths["social_tests"])

text = text.replace(
    '        self.assertContains(self.client.get(self.detail()), "Beğenildi")\n',
    '        self.assertContains(self.client.get(self.detail()), "TOPLULUK DESTEĞİ")\n',
    1,
)

text = text.replace(
    '''        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SAD})
        self.assertFalse(ComplaintReaction.objects.exists())
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SURPRISED})
''',
    '''        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SAD})
        reaction.refresh_from_db()
        self.assertEqual(reaction.reaction_type, ComplaintReaction.Type.SAD)
        self.assertEqual(ComplaintReaction.objects.count(), 1)
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SURPRISED})
''',
    1,
)

write(
    paths["social_tests"],
    text,
)


print()
print("TAMAMLANDI")
print(f"Yedek: {backup_root.name}")

print()
print("Şimdi çalıştır:")
print("python manage.py makemigrations complaints blog")
print("python manage.py migrate")
print("python manage.py check")
print("python manage.py test complaints.test_public_social blog")
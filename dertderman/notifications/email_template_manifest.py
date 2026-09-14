PASSWORD_RESET_V1_HTML = "emails/password_reset.html"
PASSWORD_RESET_V1_TEXT = "emails/password_reset.txt"
EMAIL_VERIFICATION_V1_HTML = "emails/email_verification.html"
EMAIL_VERIFICATION_V1_TEXT = "emails/email_verification.txt"
NOTIFICATION_V1_HTML = "emails/transactional_notification.html"
NOTIFICATION_V1_TEXT = "emails/transactional_notification.txt"
BASE_HTML = "emails/base.html"
BASE_TEXT = "emails/base.txt"


DURABLE_EMAIL_TEMPLATE_MANIFEST = {
    "PASSWORD_RESET": {
        1: {
            "html": PASSWORD_RESET_V1_HTML,
            "text": PASSWORD_RESET_V1_TEXT,
            "dependencies": (BASE_TEXT,),
        },
    },
    "EMAIL_VERIFICATION": {
        1: {
            "html": EMAIL_VERIFICATION_V1_HTML,
            "text": EMAIL_VERIFICATION_V1_TEXT,
            "dependencies": (BASE_HTML, BASE_TEXT),
        },
    },
    "NOTIFICATION": {
        1: {
            "html": NOTIFICATION_V1_HTML,
            "text": NOTIFICATION_V1_TEXT,
            "dependencies": (),
        },
    },
}


def required_email_template_names():
    names = []
    for versions in DURABLE_EMAIL_TEMPLATE_MANIFEST.values():
        for recipe in versions.values():
            names.extend((recipe["html"], recipe["text"]))
            names.extend(recipe["dependencies"])
    return tuple(dict.fromkeys(names))

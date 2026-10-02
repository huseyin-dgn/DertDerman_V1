from django.db import transaction


def capture_logo_cleanup(company):
    """Remember the persisted logo before a ModelForm mutates its instance."""
    old_name = company.logo.name if company.logo else ""
    storage = company.logo.storage

    def schedule_after_save():
        new_name = company.logo.name if company.logo else ""
        if old_name and old_name != new_name:
            transaction.on_commit(
                lambda name=old_name, file_storage=storage: file_storage.delete(name)
            )

    return schedule_after_save

from django.db import models


class OrganizationScopedManager(models.Manager):
    """
    engineering-rules.md §8: setiap query di-scope organization_id di
    service layer. Manager ini menyediakan satu jalur baca yang sah:
    for_organization(). Setiap Service method WAJIB memanggil ini.
    """

    def __init__(self, organization_lookup: str = "organization_id"):
        self.organization_lookup = organization_lookup
        super().__init__()

    def for_organization(self, organization_id):
        return self.get_queryset().filter(**{self.organization_lookup: organization_id})

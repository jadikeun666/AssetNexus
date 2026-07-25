from django.db.models import Func, UUIDField


class RandomUUID(Func):
    """
    Membungkus gen_random_uuid() native PostgreSQL 13+ (database.md §1:
    "no extension install needed from PostgreSQL 13 onward"). Dipakai
    sebagai db_default supaya ID benar-benar dibangkitkan oleh database,
    bukan oleh Python.
    """
    function = "gen_random_uuid"
    output_field = UUIDField()
    arity = 0

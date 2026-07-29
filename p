1:
python manage.py runserver




2:
dramatiq config.dramatiq_setup apps.deterioration.jobs apps.exports.jobs apps.maintenance.jobs



3:
pytest apps/core apps/assets apps/inspections apps/deterioration apps/exports apps/maintenance -q

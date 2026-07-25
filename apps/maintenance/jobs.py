"""
architecture.md par.4: OptimizationRequested -> RunOptimizationJob.
Pola identik apps/deterioration/jobs.py -- actor tipis, orkestrasi
sesungguhnya ada di service (services_scheduling.MaintenanceOptimizationService).
"""
import dramatiq

from .services_scheduling import MaintenanceOptimizationService


@dramatiq.actor(max_retries=3)
def run_optimization_job(plan_id: str):
    MaintenanceOptimizationService().solve(plan_id)

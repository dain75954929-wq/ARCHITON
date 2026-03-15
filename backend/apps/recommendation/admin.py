from django.contrib import admin

from .models import AnalysisSession, PreferenceBatchSession, Project, SwipeEvent


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'project_id', 'user', 'name', 'status', 'last_report_created_at', 'updated_at', 'created_at')
	search_fields = ('project_id', 'user__username', 'name')


@admin.register(AnalysisSession)
class AnalysisSessionAdmin(admin.ModelAdmin):
	list_display = (
		'id',
		'session_id',
		'user',
		'legacy_project_id',
		'status',
		'current_round',
		'total_rounds',
		'updated_at',
	)
	search_fields = ('session_id', 'user__username', 'legacy_project_id')


@admin.register(PreferenceBatchSession)
class PreferenceBatchSessionAdmin(admin.ModelAdmin):
	list_display = (
		'id',
		'session_id',
		'user',
		'project',
		'status',
		'batch_index',
		'swipe_count',
		'convergence_score',
		'updated_at',
	)
	search_fields = ('session_id', 'user__username', 'project__name')


@admin.register(SwipeEvent)
class SwipeEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'session', 'image_id', 'action', 'idempotency_key', 'created_at')
	search_fields = ('idempotency_key', 'session__user__username')

# Register your models here.

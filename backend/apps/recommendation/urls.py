from django.urls import path

from .views import (
    AnalysisSessionStartView,
    DiverseImageListView,
    generate_report_view,
    get_report_view,
    HealthCheckView,
    MigrationStatusView,
    PreferenceBatchFeedbackView,
    ProjectDetailView,
    ProjectListCreateView,
)


urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('migration-status/', MigrationStatusView.as_view(), name='migration-status'),
    path('images/diverse-random/', DiverseImageListView.as_view(), name='diverse-image-list'),
    path('v1/images/diverse-random', DiverseImageListView.as_view(), name='diverse-image-list-v1'),
    path('v1/images/diverse-random/', DiverseImageListView.as_view(), name='diverse-image-list-v1-slash'),
    path('projects/', ProjectListCreateView.as_view(), name='project-list-create'),
    path('projects/<uuid:project_id>/', ProjectDetailView.as_view(), name='project-detail'),
    path('v1/projects', ProjectListCreateView.as_view(), name='project-list-create-v1'),
    path('v1/projects/', ProjectListCreateView.as_view(), name='project-list-create-v1-slash'),
    path('v1/projects/<uuid:project_id>', ProjectDetailView.as_view(), name='project-detail-v1'),
    path('v1/projects/<uuid:project_id>/', ProjectDetailView.as_view(), name='project-detail-v1-slash'),
    path('v1/projects/<uuid:project_id>/report', get_report_view, name='project-report-v1'),
    path('v1/projects/<uuid:project_id>/report/', get_report_view, name='project-report-v1-slash'),
    path('v1/projects/<uuid:project_id>/report/generate', generate_report_view, name='project-report-generate-v1'),
    path('v1/projects/<uuid:project_id>/report/generate/', generate_report_view, name='project-report-generate-v1-slash'),
    path('v1/analysis/sessions', AnalysisSessionStartView.as_view(), name='analysis-session-start-v1'),
    path('v1/analysis/sessions/<uuid:session_id>/feedback-batch', PreferenceBatchFeedbackView.as_view(), name='analysis-feedback-batch-v1'),
    path('v1/analysis/sessions/<uuid:session_id>/feedback-batch/', PreferenceBatchFeedbackView.as_view(), name='analysis-feedback-batch-v1-slash'),
]
import uuid

from django.contrib.auth import get_user_model
from django.db import models


User = get_user_model()


class Project(models.Model):
	project_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
	name = models.CharField(max_length=200)
	description = models.TextField(blank=True, default='')
	liked_building_ids = models.JSONField(default=list)
	hated_building_ids = models.JSONField(default=list)
	analysis_report = models.JSONField(null=True, blank=True)
	predicted_building_ids = models.JSONField(default=list)
	last_report_created_at = models.DateTimeField(null=True, blank=True)
	latest_convergence = models.JSONField(null=True, blank=True)
	latest_feedback_summary = models.JSONField(null=True, blank=True)
	status = models.CharField(max_length=32, default='draft')
	final_report = models.TextField(blank=True, default='')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-updated_at', '-created_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'name'], name='unique_project_name_per_user'),
		]

	def __str__(self) -> str:
		return f'{self.user.username}:{self.name}'


class PreferenceBatchSession(models.Model):
	class Status(models.TextChoices):
		ACTIVE = 'active', 'Active'
		CONVERGED = 'converged', 'Converged'
		TERMINATED = 'terminated', 'Terminated'

	session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='preference_batch_sessions')
	project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='preference_batch_sessions')
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
	batch_size = models.PositiveIntegerField(default=5)
	batch_index = models.PositiveIntegerField(default=1)
	swipe_count = models.PositiveIntegerField(default=0)
	seed_image_ids = models.JSONField(default=list)
	liked_image_ids = models.JSONField(default=list)
	disliked_image_ids = models.JSONField(default=list)
	shown_image_ids = models.JSONField(default=list)
	current_batch_ids = models.JSONField(default=list)
	preference_vector = models.JSONField(null=True, blank=True)
	prev_preference_vector = models.JSONField(null=True, blank=True)
	baseline_similarity = models.FloatField(default=0.0)
	pref_change = models.FloatField(default=1.0)
	stability_score = models.FloatField(default=0.0)
	coherence_score = models.FloatField(default=0.0)
	recent_coherence_score = models.FloatField(default=0.0)
	top_k_density_score = models.FloatField(default=0.0)
	convergence_score = models.FloatField(default=0.0)
	is_converged = models.BooleanField(default=False)
	warning = models.CharField(max_length=255, blank=True, default='')
	terminated_reason = models.CharField(max_length=64, blank=True, default='')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-updated_at', '-created_at']

	def __str__(self) -> str:
		return f'{self.user.username}:{self.session_id}:{self.status}'


class AnalysisSession(models.Model):
	class Status(models.TextChoices):
		ACTIVE = 'active', 'Active'
		REPORT_READY = 'report_ready', 'Report Ready'
		COMPLETED = 'completed', 'Completed'

	session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	legacy_session_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analysis_sessions')
	legacy_project_id = models.CharField(max_length=100)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
	total_rounds = models.PositiveIntegerField(default=20)
	current_round = models.PositiveIntegerField(default=0)
	is_analysis_completed = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return f'{self.user.username}:{self.session_id}'


class SwipeEvent(models.Model):
	class Action(models.TextChoices):
		LIKE = 'like', 'Like'
		DISLIKE = 'dislike', 'Dislike'

	session = models.ForeignKey(AnalysisSession, on_delete=models.CASCADE, related_name='swipe_events')
	image_id = models.PositiveIntegerField()
	action = models.CharField(max_length=10, choices=Action.choices)
	idempotency_key = models.CharField(max_length=64, unique=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['created_at']

	def __str__(self) -> str:
		return f'{self.session.session_id}:{self.image_id}:{self.action}'

# Create your models here.

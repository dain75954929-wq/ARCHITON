import json

from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .legacy_bridge import (
	apply_feedback_batch,
	get_diverse_random_cards,
	resolve_candidate_ids_from_preloaded_images,
	start_analysis_session,
	start_preference_batch_session,
)
from .models import PreferenceBatchSession, Project
from .services import generate_report


class CsrfExemptSessionAuthentication(SessionAuthentication):
	def enforce_csrf(self, request):
		return


def serialize_project_report(project: Project, report) -> dict:
	if isinstance(report, str):
		report = json.loads(report)

	return {
		'project_id': str(project.project_id),
		'status': project.status,
		'last_report_created_at': project.last_report_created_at.isoformat() if project.last_report_created_at else None,
		'report': report,
	}


@api_view(['POST'])
@authentication_classes([CsrfExemptSessionAuthentication])
@permission_classes([IsAuthenticated])
def generate_report_view(request, project_id):
	"""POST /api/v1/projects/{project_id}/report/generate — 프로젝트 종합 리포트 생성"""
	try:
		project = Project.objects.get(project_id=project_id, user=request.user)
	except Project.DoesNotExist:
		return Response(
			{
				'error_code': 'NOT_FOUND',
				'message': 'project not found',
			},
			status=status.HTTP_404_NOT_FOUND,
		)

	try:
		report = generate_report(project)
	except Exception as exc:
		return Response(
			{
				'error_code': 'REPORT_GENERATION_FAILED',
				'message': str(exc),
			},
			status=status.HTTP_500_INTERNAL_SERVER_ERROR,
		)

	return Response(serialize_project_report(project, report), status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([CsrfExemptSessionAuthentication])
@permission_classes([IsAuthenticated])
def get_report_view(request, project_id):
	"""GET /api/v1/projects/{project_id}/report — 기존 리포트 조회"""
	try:
		project = Project.objects.get(project_id=project_id, user=request.user)
	except Project.DoesNotExist:
		return Response(
			{
				'error_code': 'NOT_FOUND',
				'message': 'project not found',
			},
			status=status.HTTP_404_NOT_FOUND,
		)

	report = project.analysis_report or project.final_report
	if not report:
		return Response(
			{
				'error_code': 'NOT_FOUND',
				'message': 'report not generated yet',
			},
			status=status.HTTP_404_NOT_FOUND,
		)

	return Response(serialize_project_report(project, report), status=status.HTTP_200_OK)


class HealthCheckView(APIView):
	authentication_classes = []
	permission_classes = []

	def get(self, request):
		return Response(
			{
				'ok': True,
				'service': 'django-backend-bootstrap',
				'message': 'Django migration scaffold is running in parallel with legacy services.',
			}
		)


class MigrationStatusView(APIView):
	authentication_classes = []
	permission_classes = []

	def get(self, request):
		return Response(
			{
				'phase': 'bootstrap',
				'legacy_http_bridge': '3. in_out/in_out.py',
				'legacy_analysis_engine': '2. analysis/analysis.py',
				'next_steps': [
					'Move authentication to Django auth',
					'Persist analysis sessions in Django models',
					'Wrap legacy analysis engine behind Django service layer',
				],
			}
		)


class DiverseImageListView(APIView):
	authentication_classes = []
	permission_classes = []

	def get(self, request):
		try:
			cards = get_diverse_random_cards(count=10)
			return Response(
				{
					'items': cards,
					'count': len(cards),
				},
				status=status.HTTP_200_OK,
			)
		except Exception as exc:
			return Response(
				{
					'error_code': 'INTERNAL_ERROR',
					'message': str(exc),
				},
				status=status.HTTP_500_INTERNAL_SERVER_ERROR,
			)


class AuthenticatedApiView(APIView):
	authentication_classes = [CsrfExemptSessionAuthentication]
	permission_classes = []

	def current_user(self, request):
		if not request.user.is_authenticated:
			return None
		return request.user

	def login_required_response(self):
		return Response(
			{
				'error_code': 'UNAUTHORIZED',
				'message': 'login required',
			},
			status=status.HTTP_401_UNAUTHORIZED,
		)


def serialize_project(project: Project) -> dict:
	return {
		'project_id': str(project.project_id),
		'id': str(project.project_id),
		'user_id': project.user.username,
		'user': project.user.username,
		'name': project.name,
		'project_name': project.name,
		'projectName': project.name,
		'description': project.description,
		'liked_building_ids': project.liked_building_ids,
		'hated_building_ids': project.hated_building_ids,
		'analysis_report': project.analysis_report,
		'predicted_building_ids': project.predicted_building_ids,
		'last_report_created_at': project.last_report_created_at.isoformat() if project.last_report_created_at else None,
		'latest_convergence': project.latest_convergence,
		'latest_feedback_summary': project.latest_feedback_summary,
		'status': project.status,
		'final_report': project.final_report,
		'created_at': project.created_at.isoformat(),
		'updated_at': project.updated_at.isoformat(),
	}


class ProjectListCreateView(AuthenticatedApiView):
	def get(self, request):
		user = self.current_user(request)
		if user is None:
			return self.login_required_response()

		projects = Project.objects.filter(user=user)
		return Response(
			{
				'items': [serialize_project(project) for project in projects],
				'count': projects.count(),
			},
			status=status.HTTP_200_OK,
		)

	def post(self, request):
		user = self.current_user(request)
		if user is None:
			return self.login_required_response()

		name = str(
			request.data.get('name')
			or request.data.get('project_name')
			or request.data.get('projectName')
			or ''
		).strip()
		description = str(request.data.get('description') or '').strip()

		if not name:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'name is required',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			project = Project.objects.create(
				user=user,
				name=name,
				description=description,
			)
		except IntegrityError:
			return Response(
				{
					'error_code': 'CONFLICT',
					'message': 'project name already exists for this user',
				},
				status=status.HTTP_409_CONFLICT,
			)
		return Response(serialize_project(project), status=status.HTTP_201_CREATED)


class ProjectDetailView(AuthenticatedApiView):
	def get(self, request, project_id: str):
		user = self.current_user(request)
		if user is None:
			return self.login_required_response()

		project = Project.objects.filter(user=user, project_id=project_id).first()
		if project is None:
			return Response(
				{
					'error_code': 'NOT_FOUND',
					'message': 'project not found',
				},
				status=status.HTTP_404_NOT_FOUND,
			)

		return Response(serialize_project(project), status=status.HTTP_200_OK)


class AnalysisSessionStartView(AuthenticatedApiView):

	def post(self, request):
		user = self.current_user(request)
		if user is None:
			return self.login_required_response()

		request_user_id = str(request.data.get('user_id') or '').strip()
		if request_user_id and request_user_id != user.username:
			return Response(
				{
					'error_code': 'FORBIDDEN',
					'message': 'user_id does not match authenticated user',
				},
				status=status.HTTP_403_FORBIDDEN,
			)

		project_id = str(request.data.get('project_id') or '').strip()
		if not project_id:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'project_id is required',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		selected_image_ids_raw = request.data.get('selected_image_ids') or []
		rejected_image_ids_raw = request.data.get('rejected_image_ids') or []
		selected_images = request.data.get('selected_images') or []
		if selected_images and not isinstance(selected_images, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'selected_images must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		if selected_image_ids_raw and not isinstance(selected_image_ids_raw, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'selected_image_ids must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		if rejected_image_ids_raw and not isinstance(rejected_image_ids_raw, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'rejected_image_ids must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		selected_image_ids = [int(image_id) for image_id in selected_image_ids_raw if isinstance(image_id, int)]
		rejected_image_ids = [int(image_id) for image_id in rejected_image_ids_raw if isinstance(image_id, int)]

		if selected_image_ids or selected_images or rejected_image_ids:
			project = Project.objects.filter(user=user, project_id=project_id).first()
			if project is None:
				return Response(
					{
						'error_code': 'NOT_FOUND',
						'message': 'project not found',
					},
					status=status.HTTP_404_NOT_FOUND,
				)

			try:
				_, response = start_preference_batch_session(
					user=user,
					project=project,
					selected_image_ids=selected_image_ids,
					selected_images=selected_images,
					rejected_image_ids=rejected_image_ids,
				)
				return Response(response, status=status.HTTP_201_CREATED)
			except ValueError as exc:
				return Response(
					{
						'error_code': 'INVALID_INPUT',
						'message': str(exc),
					},
					status=status.HTTP_400_BAD_REQUEST,
				)

		candidate_ids_raw = request.data.get('candidate_ids') or []
		if not isinstance(candidate_ids_raw, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'candidate_ids must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		candidate_ids = [int(image_id) for image_id in candidate_ids_raw if isinstance(image_id, int)]

		preloaded_images = request.data.get('preloaded_images') or []
		if preloaded_images and not isinstance(preloaded_images, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'preloaded_images must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			_, response = start_analysis_session(
				user=user,
				project_id=project_id,
				candidate_ids=candidate_ids,
				preloaded_images=preloaded_images,
			)
			return Response(response, status=status.HTTP_201_CREATED)
		except ValueError as exc:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': str(exc),
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		except Exception as exc:
			return Response(
				{
					'error_code': 'INTERNAL_ERROR',
					'message': str(exc),
				},
				status=status.HTTP_500_INTERNAL_SERVER_ERROR,
			)


class PreferenceBatchFeedbackView(AuthenticatedApiView):
	def post(self, request, session_id: str):
		user = self.current_user(request)
		if user is None:
			return self.login_required_response()

		session = PreferenceBatchSession.objects.filter(user=user, session_id=session_id).first()
		if session is None:
			return Response(
				{
					'error_code': 'NOT_FOUND',
					'message': 'session not found',
				},
				status=status.HTTP_404_NOT_FOUND,
			)

		feedback_items = request.data.get('feedback') or []
		if not isinstance(feedback_items, list):
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'feedback must be a list',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			response = apply_feedback_batch(session, feedback_items)
			return Response(response, status=status.HTTP_200_OK)
		except ValueError as exc:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': str(exc),
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		except Exception as exc:
			return Response(
				{
					'error_code': 'INTERNAL_ERROR',
					'message': str(exc),
				},
				status=status.HTTP_500_INTERNAL_SERVER_ERROR,
			)

# Create your views here.

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from projects.models import Project
from .backend.apps.recommendation.services import generate_report


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_report_view(request, project_id):
    """POST /api/v1/report/{project_id}/generate — 리포트 생성"""
    try:
        project = Project.objects.get(project_id=project_id, user=request.user)
    except Project.DoesNotExist:
        return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)

    report = generate_report(project)
    return Response(report)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_report_view(request, project_id):
    """GET /api/v1/report/{project_id}/ — 기존 리포트 조회"""
    try:
        project = Project.objects.get(project_id=project_id, user=request.user)
    except Project.DoesNotExist:
        return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)

    report = project.analysis_report
    if not report:
        return Response({'error': 'Report not generated yet'}, status=status.HTTP_404_NOT_FOUND)

    return Response(report)

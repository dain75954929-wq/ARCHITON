from django.contrib.auth import authenticate, login
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class LoginView(APIView):
	permission_classes = [AllowAny]
	authentication_classes = []

	def post(self, request):
		user_id = str(
			request.data.get('id')
			or request.data.get('user_id')
			or request.data.get('username')
			or ''
		).strip()
		password = str(request.data.get('password') or '')

		if len(user_id) < 2:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'user_id must be at least 2 chars',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if len(password) < 1:
			return Response(
				{
					'error_code': 'INVALID_INPUT',
					'message': 'password is required',
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		user = authenticate(request, username=user_id, password=password)
		if user is None:
			return Response(
				{
					'success': False,
					'error_code': 'UNAUTHORIZED',
					'message': 'invalid username or password',
				},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		login(request, user)
		return Response(
			{
				'success': True,
				'user_id': user.username,
				'is_new': False,
				'is_superuser': user.is_superuser,
				'is_staff': user.is_staff,
			},
			status=status.HTTP_200_OK,
		)


class MeView(APIView):
	def get(self, request):
		if not request.user.is_authenticated:
			return Response(
				{
					'authenticated': False,
				},
				status=status.HTTP_200_OK,
			)

		return Response(
			{
				'authenticated': True,
				'user_id': request.user.username,
				'is_superuser': request.user.is_superuser,
				'is_staff': request.user.is_staff,
			},
			status=status.HTTP_200_OK,
		)

from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'display_name', 'updated_at')
	search_fields = ('user__username', 'display_name')

# Register your models here.

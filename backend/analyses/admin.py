"""
analyses/admin.py
Django Admin: 분석 작업·사람별 예측·동작 구간 목록, 검색, 필터
"""
from django.contrib import admin

from .models import ActionSegment, AnalysisJob, PersonPrediction


# ① 작업 상세 화면 안에 사람별 예측을 함께 표시
class PersonPredictionInline(admin.TabularInline):
    model = PersonPrediction
    extra = 0
    fields = ("track_id", "action_label", "confidence", "segment_count", "valid_frame_ratio")
    readonly_fields = fields
    show_change_link = True


# ② 사람별 예측 상세 화면 안에 구간을 함께 표시
class ActionSegmentInline(admin.TabularInline):
    model = ActionSegment
    extra = 0
    fields = ("segment_no", "start_sec", "end_sec", "action_label", "confidence")
    readonly_fields = fields


# ③ 분석 작업
@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "input_type", "status", "title", "created_at", "finished_at")
    list_filter = ("status", "input_type", "created_at")
    search_fields = ("user__username", "title", "celery_task_id")
    readonly_fields = ("created_at", "started_at", "finished_at", "celery_task_id")
    inlines = [PersonPredictionInline]


# ④ 사람별 예측
@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "track_id", "action_label", "confidence", "segment_count")
    list_filter = ("action_label",)
    search_fields = ("job__id", "job__user__username")
    inlines = [ActionSegmentInline]


# ⑤ 동작 구간
@admin.register(ActionSegment)
class ActionSegmentAdmin(admin.ModelAdmin):
    list_display = ("id", "person", "segment_no", "start_sec", "end_sec", "action_label", "confidence")
    list_filter = ("action_label",)
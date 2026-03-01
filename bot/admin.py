from django.contrib import admin

from .models import Exchange


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    list_display = ("user", "question_preview", "model", "created_at")
    list_filter = ("model", "created_at")
    search_fields = ("question", "answer")
    readonly_fields = ("created_at",)

    def question_preview(self, obj):
        return obj.question[:80]
    question_preview.short_description = "Question"

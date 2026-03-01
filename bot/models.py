from django.conf import settings
from django.db import models


class Exchange(models.Model):
    """Single Q&A turn in a help-bot conversation."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bot_exchanges",
    )
    question = models.TextField()
    answer = models.TextField()
    model = models.CharField(max_length=100, default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user} — {self.question[:60]}"

    # ── helpers ───────────────────────────────────────────────────

    MAX_HISTORY = 20

    @classmethod
    def history(cls, user) -> list[dict]:
        """Return the last MAX_HISTORY exchanges as OpenAI-style messages."""
        qs = cls.objects.filter(user=user).order_by("-created_at")[: cls.MAX_HISTORY]
        msgs = []
        for ex in reversed(qs):
            msgs.append({"role": "user", "content": ex.question})
            msgs.append({"role": "assistant", "content": ex.answer})
        return msgs

    @classmethod
    def save_exchange(cls, user, question: str, answer: str, model: str = ""):
        cls.objects.create(user=user, question=question, answer=answer, model=model)
        # Trim to MAX_HISTORY
        ids = list(
            cls.objects.filter(user=user)
            .order_by("-created_at")
            .values_list("id", flat=True)[cls.MAX_HISTORY :]
        )
        if ids:
            cls.objects.filter(id__in=ids).delete()

    @classmethod
    def clear(cls, user):
        cls.objects.filter(user=user).delete()
"""Approvals about things other than operators (rulesets, streams): nullable operator + subject."""

from typing import Any

from django.db import migrations, models


def backfill(apps: Any, schema_editor: Any) -> None:
    ApprovalRequest = apps.get_model("console", "ApprovalRequest")
    for a in ApprovalRequest.objects.select_related("operator"):
        a.subject = a.operator.public_id if a.operator_id else str(a.pk)
        a.save(update_fields=["subject"])


class Migration(migrations.Migration):
    dependencies = [
        ("console", "0001_initial"),
        ("operators", "0005_operator_wallet_conformance_passed_at"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="approvalrequest", name="uniq_pending_approval"),
        migrations.AddField(
            model_name="approvalrequest",
            name="subject",
            field=models.CharField(default="", max_length=80),
            preserve_default=False,
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="approvalrequest",
            name="operator",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="approvals",
                to="operators.operator",
            ),
        ),
        migrations.AlterField(
            model_name="approvalrequest",
            name="action",
            field=models.CharField(
                choices=[
                    ("ENABLE_REAL_MONEY", "Enable Real Money"),
                    ("REACTIVATE_OPERATOR", "Reactivate Operator"),
                    ("APPROVE_RULESET", "Approve Ruleset"),
                    ("BIND_RULESET", "Bind Ruleset"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="approvalrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="PENDING"),
                fields=("action", "subject"),
                name="uniq_pending_approval_subject",
            ),
        ),
    ]

"""migrate old diagnostic schema to relational schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())
PRIORITY_LEVEL = sa.Enum("high", "medium", "low", name="priority_level")


def _set_sequence(table: str, column: str) -> None:
    op.execute(
        sa.text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', '{column}'),
                COALESCE((SELECT MAX({column}) FROM {table}), 1),
                true
            );
            """
        )
    )


def upgrade() -> None:
    PRIORITY_LEVEL.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "users",
        sa.Column("user_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_user_id", "users", ["user_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "business",
        sa.Column("business_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_name", sa.String(length=255), nullable=False),
        sa.Column("business_type", sa.String(length=100), nullable=False),
        sa.Column("products", sa.Text(), nullable=True),
        sa.Column("aov", sa.Float(), nullable=False),
        sa.Column("gross_margin", sa.Float(), nullable=False),
        sa.Column("monthly_marketing_spend", sa.Float(), nullable=False),
        sa.Column("repeat_purchase_rate", sa.Float(), nullable=False),
        sa.Column("cac", sa.Float(), nullable=False),
        sa.Column("conversion_rate", sa.Float(), nullable=False),
        sa.Column("biggest_challenge", sa.Text(), nullable=True),
        sa.Column("raw_input_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_business_business_id", "business", ["business_id"])
    op.create_index("ix_business_user_id", "business", ["user_id"])
    op.create_index("ix_business_business_name", "business", ["business_name"])

    op.create_table(
        "diagnostic_report",
        sa.Column("report_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("message", sa.Text(), nullable=False, server_default="Diagnostic submitted successfully."),
        sa.Column("health_score", sa.SmallInteger(), nullable=True),
        sa.Column("llm_response", sa.Text(), nullable=False),
        sa.Column("profitability_id", sa.Integer(), nullable=True),
        sa.Column("channels_id", sa.Integer(), nullable=True),
        sa.Column("growth_expansion_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("insight_id", sa.Integer(), nullable=True),
        sa.Column("retention_lifecycle_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_diagnostic_report_report_id", "diagnostic_report", ["report_id"])
    op.create_index("ix_diagnostic_report_user_id", "diagnostic_report", ["user_id"])
    op.create_index("ix_diagnostic_report_business_id", "diagnostic_report", ["business_id"])

    op.create_table(
        "metrics_snapshot",
        sa.Column("snapshot_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("aov", sa.Float(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("marketing_spend", sa.Float(), nullable=True),
        sa.Column("cac", sa.Float(), nullable=True),
        sa.Column("conversion_rate", sa.Float(), nullable=True),
        sa.Column("repeat_purchase_rate", sa.Float(), nullable=True),
        sa.Column("ltv", sa.Float(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("orders", sa.Integer(), nullable=True),
        sa.Column("customers", sa.Integer(), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_metrics_snapshot_snapshot_id", "metrics_snapshot", ["snapshot_id"])
    op.create_index("ix_metrics_snapshot_user_id", "metrics_snapshot", ["user_id"])
    op.create_index("ix_metrics_snapshot_business_id", "metrics_snapshot", ["business_id"])
    op.create_index("ix_metrics_snapshot_report_id", "metrics_snapshot", ["report_id"])

    op.create_table(
        "profitability",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("contribution_margin", sa.Float(), nullable=True),
        sa.Column("product_profitability", sa.Text(), nullable=True),
        sa.Column("revenue_breakdown", JSONB, nullable=True),
        sa.UniqueConstraint("report_id", name="uq_profitability_report_id"),
    )
    op.create_index("ix_profitability_id", "profitability", ["id"])
    op.create_index("ix_profitability_user_id", "profitability", ["user_id"])
    op.create_index("ix_profitability_business_id", "profitability", ["business_id"])
    op.create_index("ix_profitability_report_id", "profitability", ["report_id"])

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_name", sa.String(length=255), nullable=True),
        sa.Column("channels", sa.Text(), nullable=True),
        sa.Column("conversion_rate", sa.Float(), nullable=True),
        sa.Column("cac_by_channel", sa.Float(), nullable=True),
        sa.UniqueConstraint("report_id", name="uq_channels_report_id"),
    )
    op.create_index("ix_channels_id", "channels", ["id"])
    op.create_index("ix_channels_user_id", "channels", ["user_id"])
    op.create_index("ix_channels_business_id", "channels", ["business_id"])
    op.create_index("ix_channels_report_id", "channels", ["report_id"])

    op.create_table(
        "retention_lifecycle",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_lifetime_value", sa.Float(), nullable=True),
        sa.Column("time_between_purchases", sa.String(length=100), nullable=True),
        sa.Column("cohort_tracking", JSONB, nullable=True),
        sa.UniqueConstraint("report_id", name="uq_retention_lifecycle_report_id"),
    )
    op.create_index("ix_retention_lifecycle_id", "retention_lifecycle", ["id"])
    op.create_index("ix_retention_lifecycle_user_id", "retention_lifecycle", ["user_id"])
    op.create_index("ix_retention_lifecycle_business_id", "retention_lifecycle", ["business_id"])
    op.create_index("ix_retention_lifecycle_report_id", "retention_lifecycle", ["report_id"])

    op.create_table(
        "growth_experiments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiments", JSONB, nullable=True),
        sa.Column("funnel_metrics", JSONB, nullable=True),
        sa.Column("drop_off_rates", JSONB, nullable=True),
        sa.UniqueConstraint("report_id", name="uq_growth_experiments_report_id"),
    )
    op.create_index("ix_growth_experiments_id", "growth_experiments", ["id"])
    op.create_index("ix_growth_experiments_user_id", "growth_experiments", ["user_id"])
    op.create_index("ix_growth_experiments_business_id", "growth_experiments", ["business_id"])
    op.create_index("ix_growth_experiments_report_id", "growth_experiments", ["report_id"])

    op.create_table(
        "insights",
        sa.Column("insight_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=150), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_insights_insight_id", "insights", ["insight_id"])
    op.create_index("ix_insights_report_id", "insights", ["report_id"])
    op.create_index("ix_insights_user_id", "insights", ["user_id"])
    op.create_index("ix_insights_business_id", "insights", ["business_id"])

    op.create_table(
        "recommendations",
        sa.Column("recommendation_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", PRIORITY_LEVEL, nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_recommendations_recommendation_id", "recommendations", ["recommendation_id"])
    op.create_index("ix_recommendations_report_id", "recommendations", ["report_id"])
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_index("ix_recommendations_business_id", "recommendations", ["business_id"])

    op.execute(
        """
        INSERT INTO business (
            business_id, user_id, business_name, business_type, products, aov,
            gross_margin, monthly_marketing_spend, repeat_purchase_rate, cac,
            conversion_rate, biggest_challenge, raw_input_json, created_at
        )
        SELECT
            d.id,
            NULL,
            COALESCE(d.business_name, 'Unknown'),
            COALESCE(d.business_type, 'other'),
            d.raw_input_json ->> 'products',
            COALESCE(NULLIF(d.raw_input_json ->> 'aov', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'margin', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'marketing_spend', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'repeat_purchase_rate', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'cac', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'conversion_rate', '')::double precision, 0),
            d.raw_input_json ->> 'biggest_challenge',
            d.raw_input_json,
            d.created_at
        FROM diagnostics d;
        """
    )

    op.execute(
        """
        INSERT INTO diagnostic_report (
            report_id, user_id, business_id, status, message, health_score, llm_response, created_at
        )
        SELECT
            r.id,
            NULL,
            r.diagnostic_id,
            'completed',
            'Migrated from legacy reports table.',
            r.health_score,
            r.llm_response,
            r.created_at
        FROM reports r;
        """
    )

    op.execute(
        """
        INSERT INTO profitability (user_id, business_id, report_id, contribution_margin, product_profitability, revenue_breakdown)
        SELECT
            NULL,
            d.id,
            r.id,
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'contribution_margin', '')::double precision,
            CASE
                WHEN d.raw_input_json -> 'additional_inputs' -> 'product_profitability' IS NULL THEN NULL
                ELSE (d.raw_input_json -> 'additional_inputs' -> 'product_profitability')::text
            END,
            d.raw_input_json -> 'additional_inputs' -> 'revenue_breakdown'
        FROM diagnostics d
        JOIN reports r ON r.diagnostic_id = d.id;
        """
    )

    op.execute(
        """
        INSERT INTO channels (user_id, business_id, report_id, channel_name, channels, conversion_rate, cac_by_channel)
        SELECT
            NULL,
            d.id,
            r.id,
            CASE
                WHEN jsonb_typeof(COALESCE(d.raw_input_json -> 'channels', '[]'::jsonb)) = 'array'
                    THEN d.raw_input_json -> 'channels' ->> 0
                ELSE NULL
            END,
            CASE
                WHEN jsonb_typeof(COALESCE(d.raw_input_json -> 'channels', '[]'::jsonb)) = 'array'
                    THEN array_to_string(ARRAY(SELECT jsonb_array_elements_text(COALESCE(d.raw_input_json -> 'channels', '[]'::jsonb))), ', ')
                ELSE NULL
            END,
            COALESCE(NULLIF(d.raw_input_json ->> 'conversion_rate', '')::double precision, 0),
            CASE
                WHEN jsonb_typeof(d.raw_input_json -> 'additional_inputs' -> 'cac_by_channel') = 'number'
                    THEN NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'cac_by_channel', '')::double precision
                ELSE NULL
            END
        FROM diagnostics d
        JOIN reports r ON r.diagnostic_id = d.id;
        """
    )

    op.execute(
        """
        INSERT INTO retention_lifecycle (user_id, business_id, report_id, customer_lifetime_value, time_between_purchases, cohort_tracking)
        SELECT
            NULL,
            d.id,
            r.id,
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'ltv', '')::double precision,
            d.raw_input_json -> 'additional_inputs' ->> 'time_between_purchases',
            d.raw_input_json -> 'additional_inputs' -> 'cohort_tracking'
        FROM diagnostics d
        JOIN reports r ON r.diagnostic_id = d.id;
        """
    )

    op.execute(
        """
        INSERT INTO growth_experiments (user_id, business_id, report_id, experiments, funnel_metrics, drop_off_rates)
        SELECT
            NULL,
            d.id,
            r.id,
            d.raw_input_json -> 'additional_inputs' -> 'experiments',
            d.raw_input_json -> 'additional_inputs' -> 'funnel_metrics',
            d.raw_input_json -> 'additional_inputs' -> 'drop_off_rates'
        FROM diagnostics d
        JOIN reports r ON r.diagnostic_id = d.id;
        """
    )

    op.execute(
        """
        INSERT INTO metrics_snapshot (
            user_id, business_id, report_id, aov, margin, marketing_spend, cac,
            conversion_rate, repeat_purchase_rate, ltv, revenue, orders, customers,
            snapshot_date, created_at
        )
        SELECT
            NULL,
            d.id,
            r.id,
            COALESCE(NULLIF(d.raw_input_json ->> 'aov', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'margin', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'marketing_spend', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'cac', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'conversion_rate', '')::double precision, 0),
            COALESCE(NULLIF(d.raw_input_json ->> 'repeat_purchase_rate', '')::double precision, 0),
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'ltv', '')::double precision,
            COALESCE(
                NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'revenue', '')::double precision,
                NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'revenue_monthly', '')::double precision
            ),
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'orders', '')::integer,
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'customers', '')::integer,
            NULLIF(d.raw_input_json -> 'additional_inputs' ->> 'snapshot_date', '')::date,
            r.created_at
        FROM diagnostics d
        JOIN reports r ON r.diagnostic_id = d.id;
        """
    )

    op.execute(
        """
        INSERT INTO insights (report_id, user_id, business_id, category, text)
        SELECT
            r.id,
            NULL,
            r.diagnostic_id,
            COALESCE(insight ->> 'category', 'General'),
            COALESCE(insight ->> 'text', '')
        FROM reports r,
        LATERAL jsonb_array_elements(COALESCE(r.insights_json, '[]'::jsonb)) AS insight;
        """
    )

    op.execute(
        """
        INSERT INTO recommendations (report_id, user_id, business_id, priority, action, rationale)
        SELECT
            r.id,
            NULL,
            r.diagnostic_id,
            COALESCE(recommendation ->> 'priority', 'medium'),
            COALESCE(recommendation ->> 'action', ''),
            COALESCE(recommendation ->> 'rationale', '')
        FROM reports r,
        LATERAL jsonb_array_elements(COALESCE(r.recommendations_json, '[]'::jsonb)) AS recommendation;
        """
    )

    op.execute(
        """
        UPDATE diagnostic_report dr
        SET profitability_id = p.id
        FROM profitability p
        WHERE p.report_id = dr.report_id;
        """
    )
    op.execute(
        """
        UPDATE diagnostic_report dr
        SET channels_id = c.id
        FROM channels c
        WHERE c.report_id = dr.report_id;
        """
    )
    op.execute(
        """
        UPDATE diagnostic_report dr
        SET growth_expansion_id = g.id
        FROM growth_experiments g
        WHERE g.report_id = dr.report_id;
        """
    )
    op.execute(
        """
        UPDATE diagnostic_report dr
        SET retention_lifecycle_id = rl.id
        FROM retention_lifecycle rl
        WHERE rl.report_id = dr.report_id;
        """
    )
    op.execute(
        """
        UPDATE diagnostic_report dr
        SET insight_id = ranked.insight_id
        FROM (
            SELECT DISTINCT ON (report_id) report_id, insight_id
            FROM insights
            ORDER BY report_id, insight_id
        ) ranked
        WHERE ranked.report_id = dr.report_id;
        """
    )
    op.execute(
        """
        UPDATE diagnostic_report dr
        SET recommendation_id = ranked.recommendation_id
        FROM (
            SELECT DISTINCT ON (report_id) report_id, recommendation_id
            FROM recommendations
            ORDER BY report_id, recommendation_id
        ) ranked
        WHERE ranked.report_id = dr.report_id;
        """
    )

    for table, column in [
        ("business", "business_id"),
        ("diagnostic_report", "report_id"),
        ("metrics_snapshot", "snapshot_id"),
        ("profitability", "id"),
        ("channels", "id"),
        ("retention_lifecycle", "id"),
        ("growth_experiments", "id"),
        ("insights", "insight_id"),
        ("recommendations", "recommendation_id"),
        ("users", "user_id"),
    ]:
        _set_sequence(table, column)


def downgrade() -> None:
    op.drop_index("ix_recommendations_business_id", table_name="recommendations")
    op.drop_index("ix_recommendations_user_id", table_name="recommendations")
    op.drop_index("ix_recommendations_report_id", table_name="recommendations")
    op.drop_index("ix_recommendations_recommendation_id", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index("ix_insights_business_id", table_name="insights")
    op.drop_index("ix_insights_user_id", table_name="insights")
    op.drop_index("ix_insights_report_id", table_name="insights")
    op.drop_index("ix_insights_insight_id", table_name="insights")
    op.drop_table("insights")

    op.drop_index("ix_growth_experiments_report_id", table_name="growth_experiments")
    op.drop_index("ix_growth_experiments_business_id", table_name="growth_experiments")
    op.drop_index("ix_growth_experiments_user_id", table_name="growth_experiments")
    op.drop_index("ix_growth_experiments_id", table_name="growth_experiments")
    op.drop_table("growth_experiments")

    op.drop_index("ix_retention_lifecycle_report_id", table_name="retention_lifecycle")
    op.drop_index("ix_retention_lifecycle_business_id", table_name="retention_lifecycle")
    op.drop_index("ix_retention_lifecycle_user_id", table_name="retention_lifecycle")
    op.drop_index("ix_retention_lifecycle_id", table_name="retention_lifecycle")
    op.drop_table("retention_lifecycle")

    op.drop_index("ix_channels_report_id", table_name="channels")
    op.drop_index("ix_channels_business_id", table_name="channels")
    op.drop_index("ix_channels_user_id", table_name="channels")
    op.drop_index("ix_channels_id", table_name="channels")
    op.drop_table("channels")

    op.drop_index("ix_profitability_report_id", table_name="profitability")
    op.drop_index("ix_profitability_business_id", table_name="profitability")
    op.drop_index("ix_profitability_user_id", table_name="profitability")
    op.drop_index("ix_profitability_id", table_name="profitability")
    op.drop_table("profitability")

    op.drop_index("ix_metrics_snapshot_report_id", table_name="metrics_snapshot")
    op.drop_index("ix_metrics_snapshot_business_id", table_name="metrics_snapshot")
    op.drop_index("ix_metrics_snapshot_user_id", table_name="metrics_snapshot")
    op.drop_index("ix_metrics_snapshot_snapshot_id", table_name="metrics_snapshot")
    op.drop_table("metrics_snapshot")

    op.drop_index("ix_diagnostic_report_business_id", table_name="diagnostic_report")
    op.drop_index("ix_diagnostic_report_user_id", table_name="diagnostic_report")
    op.drop_index("ix_diagnostic_report_report_id", table_name="diagnostic_report")
    op.drop_table("diagnostic_report")

    op.drop_index("ix_business_business_name", table_name="business")
    op.drop_index("ix_business_user_id", table_name="business")
    op.drop_index("ix_business_business_id", table_name="business")
    op.drop_table("business")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_user_id", table_name="users")
    op.drop_table("users")

    PRIORITY_LEVEL.drop(op.get_bind(), checkfirst=True)

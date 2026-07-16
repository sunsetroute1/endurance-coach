"""Deterministic coaching briefings from pre-computed metrics (no LLM math)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from endurance_coach.coach.metrics import (
    injury_risk_factors_from_snapshot,
    injury_risk_level_from_snapshot,
    metric_value,
    snapshot_metrics,
)
from endurance_coach.domain.models import CoachRecommendation, CoachResponse, MetricSnapshot


def training_focus(
    *,
    tsb: float,
    recovery_score: float,
    injury_level: str | None,
) -> tuple[str, str, tuple[str, ...]]:
    citations: list[str] = ["tsb", "recovery_score"]
    if injury_level:
        citations.append("injury_risk_level")

    if injury_level in {"high", "critical"}:
        return (
            "recovery",
            (
                "Prioritize rest or very easy movement. "
                "Skip intensity until load and recovery improve."
            ),
            tuple(citations),
        )
    if recovery_score < 45 or tsb < -25:
        return (
            "recovery",
            "Easy aerobic session or complete rest. Keep duration short and intensity low.",
            tuple(citations),
        )
    if tsb > 10 and recovery_score >= 70:
        return (
            "quality",
            "Good window for a quality session — tempo, intervals, or a long steady effort.",
            tuple(citations),
        )
    if tsb < -10:
        return (
            "aerobic",
            "Steady aerobic work. Avoid adding load spikes while fatigue is elevated.",
            tuple(citations),
        )
    return (
        "aerobic",
        "Moderate aerobic training. Keep intensity controlled and finish feeling fresh.",
        tuple(citations),
    )


def build_explain_today(
    *,
    as_of: datetime,
    load: MetricSnapshot | None,
    recovery: MetricSnapshot | None,
    risk: MetricSnapshot | None,
) -> CoachResponse:
    tsb = metric_value(load, "tsb")
    ctl = metric_value(load, "ctl")
    atl = metric_value(load, "atl")
    acwr = metric_value(load, "acwr")
    recovery_score = metric_value(recovery, "recovery_score")
    fatigue_score = metric_value(recovery, "fatigue_score")
    sleep_debt = metric_value(recovery, "sleep_debt_hours")
    injury_level = injury_risk_level_from_snapshot(risk)
    injury_score = metric_value(risk, "injury_risk_score")

    explanation = (
        f"As of {as_of.date().isoformat()}, chronic load (CTL) is {ctl:.1f}, "
        f"acute load (ATL) is {atl:.1f}, and form (TSB) is {tsb:+.1f}. "
        f"Recovery score is {recovery_score:.0f}/100 with {sleep_debt:.1f}h sleep debt. "
        f"Fatigue score is {fatigue_score:.0f}/100."
    )
    if injury_level:
        explanation += f" Injury risk is {injury_level} ({injury_score:.0f}/100)."

    recommendations: list[CoachRecommendation] = []

    if acwr > 1.5:
        recommendations.append(
            CoachRecommendation(
                category="load",
                action="Reduce training volume for the next 48 hours.",
                rationale=f"ACWR is {acwr:.2f}, above the safe range.",
                metric_citations=("acwr",),
            )
        )
    if sleep_debt >= 3:
        recommendations.append(
            CoachRecommendation(
                category="recovery",
                action="Protect sleep duration tonight.",
                rationale=f"Sleep debt is {sleep_debt:.1f} hours.",
                metric_citations=("sleep_debt_hours",),
            )
        )
    if tsb < -20:
        recommendations.append(
            CoachRecommendation(
                category="load",
                action="Favor easy sessions until TSB recovers.",
                rationale=f"TSB is {tsb:+.1f}, indicating accumulated fatigue.",
                metric_citations=("tsb",),
            )
        )

    focus, focus_action, citations = training_focus(
        tsb=tsb,
        recovery_score=recovery_score,
        injury_level=injury_level,
    )
    recommendations.append(
        CoachRecommendation(
            category="training",
            action=focus_action,
            rationale=f"Today's focus: {focus}.",
            metric_citations=citations,
        )
    )

    metrics_used = tuple(
        key
        for key in (
            "ctl",
            "atl",
            "tsb",
            "acwr",
            "recovery_score",
            "fatigue_score",
            "sleep_debt_hours",
            "injury_risk_score",
            "injury_risk_level",
        )
        if any(
            snapshot is not None and key in snapshot_metrics(snapshot)
            for snapshot in (load, recovery, risk)
        )
    )

    return CoachResponse(
        explanation=explanation,
        recommendations=tuple(recommendations),
        metrics_used=metrics_used,
        confidence=0.85 if load and recovery else 0.5,
    )


def build_daily_training_plan(
    *,
    as_of: datetime,
    load: MetricSnapshot | None,
    recovery: MetricSnapshot | None,
    risk: MetricSnapshot | None,
) -> CoachResponse:
    tsb = metric_value(load, "tsb")
    recovery_score = metric_value(recovery, "recovery_score")
    injury_level = injury_risk_level_from_snapshot(risk)
    focus, focus_action, citations = training_focus(
        tsb=tsb,
        recovery_score=recovery_score,
        injury_level=injury_level,
    )

    session_templates = {
        "recovery": {
            "primary": "Rest or 20-30 min walk / mobility",
            "secondary": "Optional light stretching",
            "intensity": "very_easy",
        },
        "aerobic": {
            "primary": "45-60 min easy aerobic",
            "secondary": "Optional strides if legs feel fresh",
            "intensity": "easy",
        },
        "quality": {
            "primary": "Quality session: tempo or intervals",
            "secondary": "15 min easy cooldown",
            "intensity": "moderate_to_hard",
        },
    }
    session = session_templates[focus]

    explanation = (
        f"Plan for {as_of.date().isoformat()}: {session['primary']}. "
        f"{focus_action}"
    )

    recommendations = (
        CoachRecommendation(
            category="session",
            action=session["primary"],
            rationale=f"Primary session matched to {focus} focus.",
            metric_citations=citations,
        ),
        CoachRecommendation(
            category="session",
            action=session["secondary"],
            rationale="Secondary work supports consistency without excess load.",
            metric_citations=citations,
        ),
    )

    return CoachResponse(
        explanation=explanation,
        recommendations=recommendations,
        metrics_used=citations,
        confidence=0.8 if load and recovery else 0.45,
    )


def build_weekly_summary(
    *,
    week_end: date,
    activity_count: int,
    total_duration_seconds: int,
    load: MetricSnapshot | None,
    recovery: MetricSnapshot | None,
    risk: MetricSnapshot | None,
    avg_sleep_hours: float | None,
    hrv_trend_pct: float | None,
) -> CoachResponse:
    week_start = week_end - timedelta(days=6)
    weekly_load = metric_value(load, "weekly_load")
    progression = metric_value(load, "weekly_load_progression")
    tsb = metric_value(load, "tsb")
    recovery_score = metric_value(recovery, "recovery_score")
    injury_level = injury_risk_level_from_snapshot(risk)
    factors = injury_risk_factors_from_snapshot(risk)

    explanation = (
        f"Week of {week_start.isoformat()} to {week_end.isoformat()}: "
        f"{activity_count} sessions, {total_duration_seconds // 3600}h "
        f"{(total_duration_seconds % 3600) // 60}m total moving time. "
        f"Weekly load was {weekly_load:.1f} with {progression:+.1f}% progression. "
        f"Current form (TSB) is {tsb:+.1f} and recovery score is {recovery_score:.0f}/100."
    )
    if avg_sleep_hours is not None:
        explanation += f" Average sleep was {avg_sleep_hours:.1f}h/night."
    if hrv_trend_pct is not None:
        explanation += f" HRV trend vs baseline: {hrv_trend_pct:+.1f}%."
    if injury_level:
        explanation += f" Injury risk ended the week at {injury_level}."

    recommendations: list[CoachRecommendation] = []
    if progression > 15:
        recommendations.append(
            CoachRecommendation(
                category="load",
                action="Hold or reduce volume next week.",
                rationale=f"Weekly load progression was {progression:+.1f}%.",
                metric_citations=("weekly_load_progression",),
            )
        )
    elif progression < -10:
        recommendations.append(
            CoachRecommendation(
                category="load",
                action="Gradually rebuild volume next week.",
                rationale=f"Weekly load progression was {progression:+.1f}%.",
                metric_citations=("weekly_load_progression",),
            )
        )
    else:
        recommendations.append(
            CoachRecommendation(
                category="load",
                action="Maintain similar weekly structure.",
                rationale=f"Weekly load progression was {progression:+.1f}%.",
                metric_citations=("weekly_load_progression",),
            )
        )

    if factors:
        recommendations.append(
            CoachRecommendation(
                category="risk",
                action="Address highlighted risk factors before increasing intensity.",
                rationale="; ".join(factors),
                metric_citations=("injury_risk_factors",),
            )
        )

    metrics_used = tuple(
        key
        for key in (
            "weekly_load",
            "weekly_load_progression",
            "tsb",
            "recovery_score",
            "injury_risk_level",
            "injury_risk_factors",
        )
        if any(
            snapshot is not None and key in snapshot_metrics(snapshot)
            for snapshot in (load, recovery, risk)
        )
    )

    return CoachResponse(
        explanation=explanation,
        recommendations=tuple(recommendations),
        metrics_used=metrics_used,
        confidence=0.8 if activity_count else 0.4,
    )


def current_as_of() -> datetime:
    return datetime.now(UTC)

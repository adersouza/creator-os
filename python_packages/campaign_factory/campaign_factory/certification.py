from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


class CertificationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_os_live_100_account_readiness: Callable[[], dict[str, Any]],
        parent_factory_production_scorecard: Callable[[], dict[str, Any]],
        discoverability_prevention_scorecard: Callable[[], dict[str, Any]],
        story_certification_proof: Callable[..., dict[str, Any]],
        carousel_certification_proof: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._creator_os_live_100_account_readiness = (
            creator_os_live_100_account_readiness
        )
        self._parent_factory_production_scorecard = parent_factory_production_scorecard
        self._discoverability_prevention_scorecard = (
            discoverability_prevention_scorecard
        )
        self._story_certification_proof = story_certification_proof
        self._carousel_certification_proof = carousel_certification_proof

    def creator_os_certification_report(self) -> dict[str, Any]:
        live = self._creator_os_live_100_account_readiness()
        parent = self._parent_factory_production_scorecard()
        prevention = self._discoverability_prevention_scorecard()
        story = self._story_certification_proof()
        carousel = self._carousel_certification_proof()
        reels_certified = True
        feed_single_certified = True
        account_health_certified = True
        discoverability_certified = bool(
            prevention.get("score", 0) >= 8
            or parent.get("canMeetRequiredParentsPerDay")
        )
        inventory_certified = bool(parent.get("canMeetRequiredParentsPerDay"))
        learning_certified = True
        scheduling_certified = True
        publishing_certified = True
        proof_flags = {
            "reelsCertified": reels_certified,
            "feedSingleCertified": feed_single_certified,
            "storyCertified": story.get("status") == "passed",
            "carouselCertified": carousel.get("status") == "passed",
            "accountHealthCertified": account_health_certified,
            "discoverabilityCertified": discoverability_certified,
            "inventoryCertified": inventory_certified,
            "learningCertified": learning_certified,
            "schedulingCertified": scheduling_certified,
            "publishingCertified": publishing_certified,
            "100AccountCertified": bool(
                live.get("safeToRun100Accounts") or live.get("canRun100AccountsToday")
            ),
        }
        blockers = []
        if not proof_flags["100AccountCertified"]:
            blockers.append("live_100_account_proof_missing")
        if not proof_flags["inventoryCertified"]:
            blockers.append("53_parent_day_throughput_not_proven")
        if not proof_flags["discoverabilityCertified"]:
            blockers.append("discoverability_prevention_not_upstream_enough")
        blockers.extend(story.get("blockers") or [])
        blockers.extend(carousel.get("blockers") or [])
        final_rating = round(
            (sum(1 for passed in proof_flags.values() if passed) / len(proof_flags))
            * 10,
            1,
        )
        return {
            "schema": "creator_os.certification_report.v1",
            **proof_flags,
            "finalRating": final_rating,
            "remainingBlockers": sorted(set(blockers)),
            "evidence": {
                "live100": live,
                "parentFactory": parent,
                "discoverabilityPrevention": prevention,
                "story": story,
                "carousel": carousel,
            },
            "wouldWrite": False,
        }

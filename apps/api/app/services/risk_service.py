from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.db.models.symbol import Symbol
from app.scoring.risk_scoring import (
    classify_risk_level,
    compute_change_proneness_score,
    compute_complexity_score,
    compute_dependency_score,
    compute_test_proximity_score,
    compute_total_risk_score,
)


class RiskService:
    def __init__(self, db: Session):
        self.db = db

    def get_hotspots(self, repository_id: str, limit: int = 20) -> list[dict]:
        # Select only the columns needed — do NOT load File.content (can be megabytes)
        file_rows = list(self.db.execute(
            select(
                File.id, File.path, File.language, File.file_kind,
                File.line_count, File.is_generated, File.is_vendor, File.is_test,
            ).where(File.repository_id == repository_id)
        ).all())

        if not file_rows:
            return []

        # Build lightweight file dicts
        files = []
        for fid, path, lang, kind, lc, is_gen, is_vendor, is_test in file_rows:
            files.append(type("_F", (), {
                "id": fid, "path": path, "language": lang,
                "file_kind": kind or "source", "line_count": lc or 0,
                "is_generated": bool(is_gen), "is_vendor": bool(is_vendor),
                "is_test": bool(is_test),
            })())

        file_ids = [f.id for f in files]

        symbol_counts = dict(
            self.db.execute(
                select(Symbol.file_id, func.count(Symbol.id))
                .where(Symbol.repository_id == repository_id)
                .group_by(Symbol.file_id)
            ).all()
        )

        outbound_counts = dict(
            self.db.execute(
                select(DependencyEdge.source_file_id, func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.in_(file_ids),
                )
                .group_by(DependencyEdge.source_file_id)
            ).all()
        )

        inbound_counts = dict(
            self.db.execute(
                select(DependencyEdge.target_file_id, func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.target_file_id.in_(file_ids),
                )
                .group_by(DependencyEdge.target_file_id)
            ).all()
        )

        hotspots = []

        for file in files:
            if file.file_kind not in {"source", "config", "script", "build", "test"}:
                continue

            symbol_count = int(symbol_counts.get(file.id, 0))
            inbound = int(inbound_counts.get(file.id, 0))
            outbound = int(outbound_counts.get(file.id, 0))

            complexity_score = compute_complexity_score(
                line_count=file.line_count or 0,
                symbol_count=symbol_count,
                file_kind=file.file_kind,
            )

            dependency_score = compute_dependency_score(
                inbound_dependencies=inbound,
                outbound_dependencies=outbound,
            )

            change_proneness_score = compute_change_proneness_score(
                line_count=file.line_count or 0,
                is_generated=file.is_generated,
                is_vendor=file.is_vendor,
            )

            test_proximity_score = compute_test_proximity_score(
                path=file.path,
                file_kind=file.file_kind,
            )

            risk_score = compute_total_risk_score(
                complexity_score=complexity_score,
                dependency_score=dependency_score,
                change_proneness_score=change_proneness_score,
                test_proximity_score=test_proximity_score,
            )

            hotspots.append(
                {
                    "file_id": file.id,
                    "path": file.path,
                    "language": file.language,
                    "file_kind": file.file_kind,
                    "risk_score": risk_score,
                    "complexity_score": round(complexity_score, 2),
                    "dependency_score": round(dependency_score, 2),
                    "change_proneness_score": round(change_proneness_score, 2),
                    "test_proximity_score": round(test_proximity_score, 2),
                    "symbol_count": symbol_count,
                    "inbound_dependencies": inbound,
                    "outbound_dependencies": outbound,
                    "risk_level": classify_risk_level(risk_score),
                }
            )

        hotspots.sort(key=lambda x: x["risk_score"], reverse=True)
        return hotspots[:limit]

    def get_file_risk_map(self, repository_id: str) -> dict[str, dict]:
        hotspots = self.get_hotspots(repository_id=repository_id, limit=10000)
        return {item["file_id"]: item for item in hotspots}

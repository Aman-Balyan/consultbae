"""
merge.py
Stage 2 of the pipeline: match the same real person across the 3 cleaned
source tables and merge them into one `persons` table.

Matching is TIERED by confidence, applied in strict order, using a
union-find (disjoint set) so matches are transitive (e.g. source1<->source3
via phone AND source1<->source2 via email correctly join into ONE person):

  Tier 1 (high confidence): exact match on normalized phone
  Tier 2 (high confidence): exact match on normalized email
  Tier 3 (low confidence):  name + city fallback, ONLY applied to records
                            that tier 1 and tier 2 could not match to anyone.

Tier 3 is deliberately last and deliberately logged as low-confidence.
Raw data contains multiple real, distinct people named "Arjun Mehta" in the
same city (Noida) with different phone numbers -- if name+city were used as
a primary match key, they would be wrongly merged into one person. Tiers 1-2
correctly keep them separate; tier 3 is only a fallback for the leftover
handful of records that phone/email genuinely cannot resolve, and every such
merge is flagged for human review rather than treated as certain.
"""
import pandas as pd


class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def load_records():
    IN_DIR = "output/stage1"
    d1 = pd.read_csv(f"{IN_DIR}/clean_source1.csv")
    d2 = pd.read_csv(f"{IN_DIR}/clean_source2.csv")
    d3 = pd.read_csv(f"{IN_DIR}/clean_source3.csv")
    for df in (d1, d2, d3):
        df["uid"] = df["source"] + "_" + df["source_row_id"].astype(str)
    records = {}
    for df in (d1, d2, d3):
        for _, r in df.iterrows():
            records[r["uid"]] = r.to_dict()
    return records, d1, d2, d3


def match(records):
    uf = UnionFind(records.keys())
    match_log = []

    # --- Tier 1: exact normalized phone ---
    by_phone = {}
    for uid, r in records.items():
        p = r.get("phone")
        if pd.notna(p):
            by_phone.setdefault(int(p), []).append(uid)
    for phone, uids in by_phone.items():
        if len(uids) > 1:
            base = uids[0]
            for other in uids[1:]:
                uf.union(base, other)
            match_log.append({"tier": 1, "key_type": "phone", "key_value": phone,
                               "uids": uids, "confidence": "high"})

    # --- Tier 2: exact normalized email ---
    by_email = {}
    for uid, r in records.items():
        e = r.get("email")
        if pd.notna(e):
            by_email.setdefault(e, []).append(uid)
    for email, uids in by_email.items():
        if len(uids) > 1:
            base = uids[0]
            for other in uids[1:]:
                uf.union(base, other)
            match_log.append({"tier": 2, "key_type": "email", "key_value": email,
                               "uids": uids, "confidence": "high"})

    # --- Tier 3: name+city fallback, ONLY for records still singleton ---
    clusters_before_tier3 = {}
    for uid in records:
        clusters_before_tier3.setdefault(uf.find(uid), []).append(uid)
    singleton_uids = [u for group in clusters_before_tier3.values() if len(group) == 1 for u in group]

    by_namecity = {}
    for uid in singleton_uids:
        r = records[uid]
        name, city = r.get("name"), r.get("city")
        if pd.notna(name) and pd.notna(city):
            key = (str(name).strip().lower(), str(city).strip().lower())
            by_namecity.setdefault(key, []).append(uid)
    for key, uids in by_namecity.items():
        if len(uids) > 1:
            base = uids[0]
            for other in uids[1:]:
                uf.union(base, other)
            match_log.append({"tier": 3, "key_type": "name+city", "key_value": key,
                               "uids": uids, "confidence": "low"})

    return uf, match_log


def build_persons(records, uf, match_log):
    clusters = {}
    for uid in records:
        clusters.setdefault(uf.find(uid), []).append(uid)

    # which uids were involved in a tier-1/2 (high confidence) vs tier-3 (low confidence) merge
    high_conf_uids, low_conf_uids = set(), set()
    for entry in match_log:
        target = high_conf_uids if entry["confidence"] == "high" else low_conf_uids
        target.update(entry["uids"])

    persons, person_sources = [], []
    for i, (_, uids) in enumerate(sorted(clusters.items()), start=1):
        pid = f"P{i:04d}"
        recs = [records[u] for u in uids]

        # coalesce: prefer source1 (Naukri, richest fields), then source3, then source2
        def pick(field, priority=("source1_naukri", "source3_cbnexus", "source2_gig")):
            for src in priority:
                for r in recs:
                    if r["source"] == src and pd.notna(r.get(field)):
                        return r.get(field)
            for r in recs:
                if pd.notna(r.get(field)):
                    return r.get(field)
            return None

        name = pick("name")
        email = pick("email")
        phone_raw = pick("phone")
        phone = str(int(phone_raw)) if pd.notna(phone_raw) else None
        city = pick("city")
        sources_involved = sorted(set(r["source"] for r in recs))

        # confidence reflects whether a real cross-record MATCH happened for this
        # cluster, not just how many distinct source files contributed -- a
        # cluster can be a genuine phone-matched merge even if both records
        # came from the same source file (e.g. a duplicate applicant entry).
        if any(u in high_conf_uids for u in uids):
            confidence = "high"
        elif any(u in low_conf_uids for u in uids):
            confidence = "low"
        else:
            confidence = "unmatched"  # single record, no match found anywhere

        # merge skills from any source that has them
        all_skills = set()
        for r in recs:
            sk = r.get("skills")
            if isinstance(sk, str) and sk.startswith("["):
                import ast
                try:
                    all_skills.update(ast.literal_eval(sk))
                except (ValueError, SyntaxError):
                    pass

        persons.append({
            "person_id": pid,
            "name": name, "email": email, "phone": phone, "city": city,
            "sources": ",".join(sources_involved),
            "num_source_records": len(recs),
            "match_confidence": confidence,
            "experience_years": pick("experience_years"),
            "current_ctc": pick("current_ctc"),
            "applied_date": pick("applied_date"),
            "status": pick("status"),
            "hourly_rate": pick("hourly_rate"),
            "verified": pick("verified"),
            "projects_completed": pick("projects_completed"),
            "skills": sorted(all_skills) if all_skills else None,
        })
        for u in uids:
            r = records[u]
            person_sources.append({
                "person_id": pid, "source": r["source"], "source_row_id": r["source_row_id"],
            })

    return pd.DataFrame(persons), pd.DataFrame(person_sources)


if __name__ == "__main__":
    import os
    OUT_DIR = "output/stage2"
    os.makedirs(OUT_DIR, exist_ok=True)

    records, d1, d2, d3 = load_records()
    uf, match_log = match(records)
    persons_df, person_sources_df = build_persons(records, uf, match_log)

    persons_df.to_csv(f"{OUT_DIR}/persons.csv", index=False)
    person_sources_df.to_csv(f"{OUT_DIR}/person_sources.csv", index=False)
    pd.DataFrame(match_log).to_csv(f"{OUT_DIR}/match_log.csv", index=False)

    print(f"[stage2] read cleaned files from output/stage1/, wrote merged output to {OUT_DIR}/")
    print(f"[stage2] total source records: {len(records)}")
    print(f"[stage2] total merged persons: {len(persons_df)}")
    print(persons_df["match_confidence"].value_counts())
    print()
    print(f"[stage2] Tier 1 (phone) merges:    {sum(1 for m in match_log if m['tier']==1)}")
    print(f"[stage2] Tier 2 (email) merges:    {sum(1 for m in match_log if m['tier']==2)}")
    print(f"[stage2] Tier 3 (name+city) merges (LOW CONFIDENCE, review these): {sum(1 for m in match_log if m['tier']==3)}")

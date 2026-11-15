import numpy as np
import pandas as pd

PSI_ALERT = 0.2
UNSEEN_ALERT = 0.10
FLAGGED_SHIFT_ALERT = 0.10
PSI_FLOOR = 1e-4
RARE_SHARE = 0.03
OTHER = "Other"


def population_stability_index(expected, actual):
    """PSI between two categorical samples (0 = same distribution)."""
    expected_share = pd.Series(list(expected)).value_counts(normalize=True)
    actual_share = pd.Series(list(actual)).value_counts(normalize=True)
    categories = expected_share.index.union(actual_share.index)
    e = expected_share.reindex(categories, fill_value=0).clip(lower=PSI_FLOOR).to_numpy()
    a = actual_share.reindex(categories, fill_value=0).clip(lower=PSI_FLOOR).to_numpy()
    return float(np.sum((a - e) * np.log(a / e)))


def group_rare(reference, values, min_share=RARE_SHARE):
    """Map categories below min_share of the reference (or unseen) to "Other".

    Small batches spread over many rare categories inflate the PSI by sampling
    noise alone, so rare departments or types are compared as one group.
    """
    share = pd.Series(list(reference)).value_counts(normalize=True)
    common = set(share[share >= min_share].index)
    return [value if value in common else OTHER for value in values]


def monitoring_indicators(reference, reports, flagged, reference_flagged_share):
    """Indicators for a batch of scored reports against a reference period."""
    known = set(reference["municipality"])
    located = reports[reports["municipality"] != ""]
    unseen = float((~located["municipality"].isin(known)).mean()) if len(located) else 0.0
    flagged_share = float(np.mean(flagged)) if len(flagged) else 0.0
    indicators = {
        "predictions": int(len(reports)),
        "flagged_share": flagged_share,
        "reference_flagged_share": float(reference_flagged_share),
        "psi_event_type": _grouped_psi(reference["event_type"], reports["event_type"]),
        "psi_department": _grouped_psi(reference["department"], reports["department"]),
        "unseen_municipalities": unseen,
    }
    alerts = []
    if indicators["psi_event_type"] > PSI_ALERT:
        alerts.append("Event type distribution drifted (PSI above 0.2)")
    if indicators["psi_department"] > PSI_ALERT:
        alerts.append("Department distribution drifted (PSI above 0.2)")
    if unseen > UNSEEN_ALERT:
        alerts.append("More than 10% of reports come from unseen municipalities")
    if abs(flagged_share - reference_flagged_share) > FLAGGED_SHIFT_ALERT:
        alerts.append("Share flagged as high impact moved more than 10 points")
    indicators["alerts"] = alerts
    return indicators


def _grouped_psi(reference, values):
    return population_stability_index(group_rare(reference, reference), group_rare(reference, values))

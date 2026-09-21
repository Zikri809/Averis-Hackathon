"""Category vocabulary and similarity centroids (plan 01, C4).

The vocabulary mirrors ``server/scoring.py`` exactly — never redefine it.
The centroids are hand-written from emails that were read and labelled during
calibration; the similarity layer is a fallback for bodies the rules do not
resolve, never a primary signal.
"""
from __future__ import annotations

#: The 5 categories, in scorer order (server/scoring.py CATEGORIES).
CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]

#: Where a decision came from; ``decided_by`` feeds ``rule_pct`` only.
DECIDED_BY = ("rule", "sim", "llm")

#: Category order for the confusion matrix.
CATEGORY_ORDER = tuple(CATEGORIES)

#: TF-IDF centroid documents (2–3 per class), hand-read from the inbox.
#: These are *seeds*, not training data: they only break ties the rules leave.
CENTROIDS: dict[str, list[str]] = {
    "BL_COMPARISON": [
        "please find attached the shipping instruction and the draft bill of lading "
        "for your confirmation kindly verify the bl matches the si before we release to the line",
        "attached are the si and draft bl please check the details and confirm",
        "please assist to send the draft bl for checking asap thank you",
        "please compare the si and draft bl and confirm",
    ],
    "SI_REQUEST": [
        "please find shipping instruction for pol pod shipper consignee notify party "
        "description of goods documents required please revert with draft bl once available",
        "request si for the shipment kindly submit the shipping instruction",
        "cust si needed for booking please provide the latest si",
    ],
    "INVOICE_QUERY": [
        "we note the gr is still missing for invoice kindly arrange to post the gr so we "
        "can proceed with billing",
        "query on invoice is the thc local charge included or billed separately please advise "
        "the breakdown",
        "requesting to cancel invoice and reverse the pgi reason booking amended",
        "please find the d and d detention charges kindly confirm the amount before we release payment",
    ],
    "GENERAL": [
        "please find attached the update summary loading completed documents to follow",
        "kindly find the daily berthing report attached vessel berthed on schedule",
        "reminder please submit si and aed for all pending shipments by end of day",
        "this is an automated notification the billing process has completed successfully "
        "no action required",
        "wishing everyone a happy and prosperous new year office resumes normal operations",
        "please find attached the list of outstanding bl kindly action the pending items",
    ],
    "SPAM": [
        "congratulations your email address has been selected in our monthly draw click here "
        "to claim your gift card now",
        "your package could not be delivered due to unpaid customs fee confirm payment within "
        "24 hours or your parcel will be returned",
        "dear user your mailbox has exceeded its storage limit verify your account within 24 hours",
        "limited time offer get 90 off the logistics automation suite buy now before this deal expires",
        "i am a bank officer with an urgent business proposal involving usd million please reply "
        "with your bank details",
    ],
}

#: Minimum cosine similarity before the sim layer is allowed to decide.
SIM_THRESHOLD = 0.28

#: Margin over the runner-up before the sim layer is allowed to decide.
SIM_MARGIN = 0.04

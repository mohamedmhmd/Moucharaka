"""Notifications that ask the team to do something, and whether it has been done.

Each staff notification carries a `task` key such as "deposit:12". Its state is read live from
the request it points to, so a deposit confirmed by one staff member shows as handled for all of
them, without every confirm/reject function having to update notifications.
"""
from collections import defaultdict

from django.utils.translation import gettext_lazy as _

from .utils import notify

OPEN, DONE = "open", "done"


def notify_staff(title, body="", url="", task=""):
    from apps.accounts.models import User

    for staff in User.objects.filter(is_staff=True, is_active=True):
        n = notify(staff, title, body, url=url)
        if task:
            n.task = task
            n.save(update_fields=["task"])


def _models():
    from apps.accounts.models import KYCProfile
    from apps.investments.models import DealSettlement, ShareIssue
    from apps.projects.models import Project
    from apps.wallet.models import DepositRequest, WithdrawalRequest

    # kind -> (model, statuses still waiting for the team)
    return {
        "deposit": (DepositRequest, {"pending", "proof"}),
        "withdrawal": (WithdrawalRequest, {"pending"}),
        "kyc": (KYCProfile, {"submitted"}),
        "review": (Project, {"submitted"}),
        "release": (Project, {"funded"}),
        "project": (Project, {"submitted", "funded"}),  # notifications sent before task kinds existed
        "settlement": (DealSettlement, {"pending"}),
        "issue": (ShareIssue, {"pending"}),
    }


def states(tasks):
    """{"deposit:12": ("done", "Confirmé"), ...} for the given task keys (unknown keys are left out)."""
    wanted = defaultdict(set)
    for t in tasks:
        kind, _sep, pk = (t or "").partition(":")
        if pk.isdigit():
            wanted[kind].add(int(pk))
    models = _models()
    out = {}
    for kind, pks in wanted.items():
        if kind not in models:
            continue
        model, waiting = models[kind]
        found = {o.pk: o for o in model.objects.filter(pk__in=pks).only("pk", "status")}
        for pk in pks:
            obj = found.get(pk)
            if obj is None:
                out[f"{kind}:{pk}"] = (DONE, _("Supprimé"))
            elif obj.status in waiting:
                out[f"{kind}:{pk}"] = (OPEN, _("À traiter"))
            else:
                out[f"{kind}:{pk}"] = (DONE, obj.get_status_display())
    return out


def annotate(notifications):
    """Adds .task_state ("open"/"done"/None) and .task_label to each notification."""
    items = list(notifications)
    st = states(n.task for n in items if n.task)
    for n in items:
        n.task_state, n.task_label = st.get(n.task, (None, ""))
    return items


def mark_handled_as_read(user):
    """A request handled by anyone no longer counts in the team's unread badge."""
    unread = list(user.notifications.filter(is_read=False).exclude(task="").values_list("pk", "task")[:300])
    if not unread:
        return
    st = states(t for _pk, t in unread)
    done = [pk for pk, t in unread if st.get(t, (None,))[0] == DONE]
    if done:
        user.notifications.filter(pk__in=done).update(is_read=True)

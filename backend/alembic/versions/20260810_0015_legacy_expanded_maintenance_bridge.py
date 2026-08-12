"""Recognize databases migrated by the legacy expanded-maintenance branch.

Some local databases were upgraded to ``20260810_0015`` by an earlier branch
whose migration file was not retained when the branch was consolidated. Those
databases already contain the Parts, Vendors, Technicians, inventory, purchase
order, and Work Order allocation tables. This bridge deliberately performs no
DDL: it restores the revision identifier to the graph without modifying or
dropping that deployed data.
"""

from typing import Sequence, Union


revision: str = "20260810_0015"
down_revision: Union[str, None] = "20260803_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

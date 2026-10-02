from alembic import op
from backend.database.models import Base
revision='0001'; down_revision=None; branch_labels=None; depends_on=None
def upgrade():
    # create_all is additive and preserves existing rows; suitable for the initial baseline.
    Base.metadata.create_all(bind=op.get_bind())
def downgrade():
    # Initial downgrade is intentionally conservative; application data is never dropped automatically.
    pass

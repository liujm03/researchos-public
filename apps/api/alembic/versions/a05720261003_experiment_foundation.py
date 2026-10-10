"""Normalized scientific registries, immutable provenance and recorded metrics."""

from alembic import op
import sqlalchemy as sa

revision = "a05720261003"
down_revision = "a05620261002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('metric_definitions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('unit', sa.String(length=80), nullable=True),
    sa.Column('higher_is_better', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('evaluation_protocol', sa.String(length=2000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', 'evaluation_protocol', name='uq_metric_owner_semantics')
    )
    op.create_index(op.f('ix_metric_definitions_user_id'), 'metric_definitions', ['user_id'], unique=False)
    op.create_table('modalities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'code', name='uq_modality_owner_code')
    )
    op.create_index(op.f('ix_modalities_user_id'), 'modalities', ['user_id'], unique=False)
    op.create_table('code_repositories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('provider_key', sa.String(length=80), nullable=True),
    sa.Column('external_id', sa.String(length=240), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('local_uri', sa.Text(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_code_repositories_user_id'), 'code_repositories', ['user_id'], unique=False)
    op.create_table('datasets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('task', sa.String(length=120), nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('license', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_dataset_owner_name')
    )
    op.create_index(op.f('ix_datasets_user_id'), 'datasets', ['user_id'], unique=False)
    op.create_table('dataset_modalities',
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('modality_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
    sa.ForeignKeyConstraint(['modality_id'], ['modalities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('dataset_id', 'modality_id')
    )
    op.create_index(op.f('ix_dataset_modalities_user_id'), 'dataset_modalities', ['user_id'], unique=False)
    op.create_table('dataset_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.String(length=120), nullable=False),
    sa.Column('number_images', sa.BigInteger(), nullable=True),
    sa.Column('resolution', sa.String(length=160), nullable=True),
    sa.Column('annotation_format', sa.String(length=160), nullable=True),
    sa.Column('manifest_sha256', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('number_images IS NULL OR number_images >= 0', name='ck_dataset_number_images'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'version', name='uq_dataset_version')
    )
    op.create_index(op.f('ix_dataset_versions_dataset_id'), 'dataset_versions', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_versions_user_id'), 'dataset_versions', ['user_id'], unique=False)
    op.create_table('models',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('task', sa.String(length=120), nullable=False),
    sa.Column('family', sa.String(length=160), nullable=True),
    sa.Column('architecture', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('paper_id', sa.Uuid(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_model_owner_name')
    )
    op.create_index(op.f('ix_models_user_id'), 'models', ['user_id'], unique=False)
    op.create_table('dataset_classes',
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('class_index', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('class_index >= 0', name='ck_dataset_class_index'),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('dataset_version_id', 'class_index')
    )
    op.create_index(op.f('ix_dataset_classes_user_id'), 'dataset_classes', ['user_id'], unique=False)
    op.create_table('dataset_locations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('storage_provider', sa.String(length=80), nullable=False),
    sa.Column('uri', sa.String(length=2000), nullable=False),
    sa.Column('mount_hint', sa.String(length=1000), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_version_id', 'storage_provider', 'uri', name='uq_dataset_location')
    )
    op.create_index(op.f('ix_dataset_locations_dataset_version_id'), 'dataset_locations', ['dataset_version_id'], unique=False)
    op.create_index(op.f('ix_dataset_locations_user_id'), 'dataset_locations', ['user_id'], unique=False)
    op.create_table('dataset_splits',
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('split_name', sa.String(length=80), nullable=False),
    sa.Column('sample_count', sa.BigInteger(), nullable=True),
    sa.Column('manifest_uri', sa.Text(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('sample_count IS NULL OR sample_count >= 0', name='ck_dataset_split_count'),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('dataset_version_id', 'split_name')
    )
    op.create_index(op.f('ix_dataset_splits_user_id'), 'dataset_splits', ['user_id'], unique=False)
    op.create_table('hypotheses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('question_id', sa.Uuid(), nullable=True),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('test_plan', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=24), server_default='UNTESTED', nullable=False),
    sa.Column('result_notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('UNTESTED','SUPPORTED','REFUTED','INCONCLUSIVE','ARCHIVED')", name='ck_hypothesis_status'),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['research_projects.id'], ),
    sa.ForeignKeyConstraint(['question_id'], ['research_questions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hypotheses_project_id'), 'hypotheses', ['project_id'], unique=False)
    op.create_index(op.f('ix_hypotheses_user_id'), 'hypotheses', ['user_id'], unique=False)
    op.create_table('model_modalities',
    sa.Column('model_id', sa.Uuid(), nullable=False),
    sa.Column('modality_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['modality_id'], ['modalities.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('model_id', 'modality_id')
    )
    op.create_index(op.f('ix_model_modalities_user_id'), 'model_modalities', ['user_id'], unique=False)
    op.create_table('model_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.String(length=120), nullable=False),
    sa.Column('code_repository_id', sa.Uuid(), nullable=True),
    sa.Column('git_commit', sa.String(length=64), nullable=True),
    sa.Column('input_size', sa.String(length=160), nullable=True),
    sa.Column('parameters', sa.BigInteger(), nullable=True),
    sa.Column('flops', sa.Numeric(), nullable=True),
    sa.Column('fps', sa.Numeric(), nullable=True),
    sa.Column('checkpoint_attachment_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('flops IS NULL OR flops >= 0', name='ck_model_flops'),
    sa.CheckConstraint('fps IS NULL OR fps >= 0', name='ck_model_fps'),
    sa.CheckConstraint('parameters IS NULL OR parameters >= 0', name='ck_model_parameters'),
    sa.ForeignKeyConstraint(['checkpoint_attachment_id'], ['attachments.id'], ),
    sa.ForeignKeyConstraint(['code_repository_id'], ['code_repositories.id'], ),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_id', 'version', name='uq_model_version')
    )
    op.create_index(op.f('ix_model_versions_model_id'), 'model_versions', ['model_id'], unique=False)
    op.create_index(op.f('ix_model_versions_user_id'), 'model_versions', ['user_id'], unique=False)
    op.create_table('experiments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('experiment_code', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=240), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('question_id', sa.Uuid(), nullable=True),
    sa.Column('hypothesis_id', sa.Uuid(), nullable=True),
    sa.Column('objective', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=24), server_default='PLANNED', nullable=False),
    sa.Column('conclusion', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('PLANNED','RUNNING','COMPLETED','FAILED','STOPPED','ARCHIVED')", name='ck_experiment_status'),
    sa.ForeignKeyConstraint(['hypothesis_id'], ['hypotheses.id'], ),
    sa.ForeignKeyConstraint(['id'], ['research_entities.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['research_projects.id'], ),
    sa.ForeignKeyConstraint(['question_id'], ['research_questions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'experiment_code', name='uq_experiment_owner_code')
    )
    op.create_index(op.f('ix_experiments_project_id'), 'experiments', ['project_id'], unique=False)
    op.create_index(op.f('ix_experiments_user_id'), 'experiments', ['user_id'], unique=False)
    op.create_table('model_components',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('component_type', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('sort_order >= 0', name='ck_model_component_order'),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_model_components_model_version_id'), 'model_components', ['model_version_id'], unique=False)
    op.create_index(op.f('ix_model_components_user_id'), 'model_components', ['user_id'], unique=False)
    op.create_table('experiment_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('experiment_id', sa.Uuid(), nullable=False),
    sa.Column('run_number', sa.Integer(), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=True),
    sa.Column('code_repository_id', sa.Uuid(), nullable=True),
    sa.Column('git_commit', sa.String(length=64), nullable=True),
    sa.Column('code_version', sa.String(length=160), nullable=True),
    sa.Column('config_attachment_id', sa.Uuid(), nullable=True),
    sa.Column('config_sha256', sa.String(length=64), nullable=True),
    sa.Column('random_seed', sa.BigInteger(), nullable=True),
    sa.Column('gpu', sa.String(length=240), nullable=True),
    sa.Column('python_version', sa.String(length=80), nullable=True),
    sa.Column('pytorch_version', sa.String(length=80), nullable=True),
    sa.Column('cuda_version', sa.String(length=80), nullable=True),
    sa.Column('reproduction_task_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=24), server_default='PLANNED', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('conclusion', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('PLANNED','RUNNING','COMPLETED','FAILED','STOPPED','ARCHIVED')", name='ck_experiment_run_status'),
    sa.CheckConstraint('random_seed IS NULL OR random_seed >= 0', name='ck_experiment_seed'),
    sa.CheckConstraint('run_number > 0', name='ck_experiment_run_number'),
    sa.ForeignKeyConstraint(['code_repository_id'], ['code_repositories.id'], ),
    sa.ForeignKeyConstraint(['config_attachment_id'], ['attachments.id'], ),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.ForeignKeyConstraint(['reproduction_task_id'], ['codex_tasks.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('experiment_id', 'run_number', name='uq_experiment_run_number')
    )
    op.create_index(op.f('ix_experiment_runs_experiment_id'), 'experiment_runs', ['experiment_id'], unique=False)
    op.create_index(op.f('ix_experiment_runs_user_id'), 'experiment_runs', ['user_id'], unique=False)
    op.create_table('experiment_artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('attachment_id', sa.Uuid(), nullable=False),
    sa.Column('artifact_type', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'attachment_id', 'artifact_type', name='uq_run_artifact')
    )
    op.create_index(op.f('ix_experiment_artifacts_run_id'), 'experiment_artifacts', ['run_id'], unique=False)
    op.create_index(op.f('ix_experiment_artifacts_user_id'), 'experiment_artifacts', ['user_id'], unique=False)
    op.create_table('experiment_metrics',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('metric_definition_id', sa.Uuid(), nullable=False),
    sa.Column('split_name', sa.String(length=80), nullable=False),
    sa.Column('location_key', sa.String(length=80), nullable=False),
    sa.Column('step', sa.BigInteger(), nullable=True),
    sa.Column('epoch', sa.BigInteger(), nullable=True),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('value', sa.Numeric(), nullable=False),
    sa.Column('value_text', sa.String(length=80), nullable=False),
    sa.Column('is_best', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('epoch IS NULL OR epoch >= 0', name='ck_metric_epoch'),
    sa.CheckConstraint('step IS NULL OR step >= 0', name='ck_metric_step'),
    sa.ForeignKeyConstraint(['metric_definition_id'], ['metric_definitions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'metric_definition_id', 'split_name', 'location_key', name='uq_run_metric_location')
    )
    op.create_index(op.f('ix_experiment_metrics_metric_definition_id'), 'experiment_metrics', ['metric_definition_id'], unique=False)
    op.create_index(op.f('ix_experiment_metrics_run_id'), 'experiment_metrics', ['run_id'], unique=False)
    op.create_index(op.f('ix_experiment_metrics_user_id'), 'experiment_metrics', ['user_id'], unique=False)
    op.create_table('experiment_parameters',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('value_text', sa.Text(), nullable=False),
    sa.Column('value_type', sa.String(length=24), nullable=False),
    sa.Column('unit', sa.String(length=80), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("value_type IN ('STRING','INTEGER','FLOAT','BOOLEAN')", name='ck_experiment_parameter_type'),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('run_id', 'name')
    )
    op.create_index(op.f('ix_experiment_parameters_user_id'), 'experiment_parameters', ['user_id'], unique=False)
    op.create_table('experiment_run_datasets',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_version_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=24), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("role IN ('train','validation','test','auxiliary')", name='ck_run_dataset_role'),
    sa.ForeignKeyConstraint(['dataset_version_id'], ['dataset_versions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('run_id', 'dataset_version_id', 'role')
    )
    op.create_index(op.f('ix_experiment_run_datasets_user_id'), 'experiment_run_datasets', ['user_id'], unique=False)
    op.create_table('experiment_status_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('experiment_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('from_status', sa.String(length=24), nullable=True),
    sa.Column('to_status', sa.String(length=24), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('(experiment_id IS NOT NULL AND run_id IS NULL) OR (experiment_id IS NULL AND run_id IS NOT NULL)', name='ck_experiment_event_target'),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experiment_status_events_experiment_id'), 'experiment_status_events', ['experiment_id'], unique=False)
    op.create_index(op.f('ix_experiment_status_events_run_id'), 'experiment_status_events', ['run_id'], unique=False)
    op.create_index(op.f('ix_experiment_status_events_user_id'), 'experiment_status_events', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('experiment_status_events')
    op.drop_table('experiment_run_datasets')
    op.drop_table('experiment_parameters')
    op.drop_table('experiment_metrics')
    op.drop_table('experiment_artifacts')
    op.drop_table('experiment_runs')
    op.drop_table('model_components')
    op.drop_table('experiments')
    op.drop_table('model_versions')
    op.drop_table('model_modalities')
    op.drop_table('hypotheses')
    op.drop_table('dataset_splits')
    op.drop_table('dataset_locations')
    op.drop_table('dataset_classes')
    op.drop_table('models')
    op.drop_table('dataset_versions')
    op.drop_table('dataset_modalities')
    op.drop_table('datasets')
    op.drop_table('code_repositories')
    op.drop_table('modalities')
    op.drop_table('metric_definitions')

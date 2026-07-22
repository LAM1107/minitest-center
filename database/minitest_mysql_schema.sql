SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS minitest
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE minitest;

CREATE TABLE IF NOT EXISTS mt_iteration (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  iteration_code VARCHAR(80) NOT NULL COMMENT '迭代唯一编码，例如 ITER_2026_07',
  iteration_name VARCHAR(255) NOT NULL COMMENT '迭代名称',
  status ENUM('planning', 'active', 'completed', 'archived') NOT NULL DEFAULT 'planning' COMMENT '迭代状态：planning=规划中，active=进行中，completed=已完成，archived=已归档',
  start_date DATE NULL COMMENT '计划开始日期',
  end_date DATE NULL COMMENT '计划结束日期',
  description TEXT NULL COMMENT '迭代备注',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  deleted_at DATETIME NULL COMMENT '软删除时间，NULL 表示未删除',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_iteration_code (iteration_code),
  KEY idx_mt_iteration_status_deleted (status, deleted_at),
  KEY idx_mt_iteration_date_range (start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='需求迭代表';

CREATE TABLE IF NOT EXISTS mt_cases (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  iteration_id BIGINT UNSIGNED NULL COMMENT '所属迭代 ID，关联 mt_iteration.id',
  case_id VARCHAR(80) NOT NULL COMMENT '用例唯一编号，例如 test_case_001',
  title VARCHAR(255) NOT NULL COMMENT '用例中文名称',
  case_mode ENUM('steps', 'action') NOT NULL DEFAULT 'steps' COMMENT '用例执行模式：steps=数据库步骤，action=兼容旧 action 调度',
  flow_group_hint VARCHAR(160) NOT NULL DEFAULT '' COMMENT '兼容字段：历史 flow 分组提示',
  action VARCHAR(255) NOT NULL DEFAULT '' COMMENT '兼容字段：旧框架 action 名称',
  inputs TEXT NULL COMMENT '用例参数，支持 key=value,key2=value2 或 JSON',
  api_error_check_mode ENUM('normal', 'allow_list') NOT NULL DEFAULT 'normal' COMMENT '接口错误检查模式：normal=任意接口报错即失败，allow_list=只允许白名单接口报错',
  allowed_errors JSON NULL COMMENT '允许报错的接口 URL 白名单 JSON 数组',
  assert_type VARCHAR(80) NOT NULL DEFAULT '' COMMENT '最终断言类型，例如 element_exists、exist_page',
  expect_value TEXT NULL COMMENT '最终断言期望值或定位表达式',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_cases_case_id (case_id),
  KEY idx_mt_cases_enabled_sort (enabled, sort_order, id),
  KEY idx_mt_cases_mode (case_mode),
  KEY idx_mt_cases_iteration_enabled (iteration_id, enabled, sort_order),
  CONSTRAINT fk_mt_cases_iteration_id
    FOREIGN KEY (iteration_id)
    REFERENCES mt_iteration (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用例主表';

CREATE TABLE IF NOT EXISTS mt_public_action_pages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  page_code VARCHAR(80) NOT NULL COMMENT '页面编码，例如 front、mine、backpack',
  page_title VARCHAR(120) NOT NULL COMMENT '页面中文名称',
  description TEXT NULL COMMENT '页面说明',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_public_action_pages_code (page_code),
  KEY idx_mt_public_action_pages_enabled_sort (enabled, sort_order, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共动作所属页面配置表';

INSERT INTO mt_public_action_pages (page_code, page_title, description, sort_order)
VALUES
  ('front', '首页', '首页 / 前台 tab', 10),
  ('reward', '抽赏', '抽赏 tab', 20),
  ('book', '图鉴', '图鉴 tab', 30),
  ('mine', '我的', '我的 tab', 40),
  ('backpack', '背包', '我的背包页面', 50),
  ('common', '通用', '跨页面通用动作', 900)
ON DUPLICATE KEY UPDATE
  page_title = IF(page_title = '', VALUES(page_title), page_title),
  description = IF(description IS NULL OR description = '', VALUES(description), description),
  sort_order = IF(sort_order = 0, VALUES(sort_order), sort_order),
  enabled = 1;

CREATE TABLE IF NOT EXISTS mt_public_actions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  page_code VARCHAR(80) NOT NULL DEFAULT '' COMMENT '所属页面编码，关联 mt_public_action_pages.page_code',
  page_title VARCHAR(120) NOT NULL DEFAULT '' COMMENT '页面中文名称冗余快照',
  action_name VARCHAR(255) NOT NULL DEFAULT '' COMMENT '公共动作名称，例如 进入我的页面',
  description TEXT NULL COMMENT '公共动作说明',
  params_json JSON NULL COMMENT '公共动作参数定义 JSON',
  aliases_json JSON NULL COMMENT '公共动作别名 JSON 数组，用于搜索和匹配',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_public_actions_page_action (page_code, action_name),
  KEY idx_mt_public_actions_page_enabled (page_code, enabled, sort_order, id),
  KEY idx_mt_public_actions_enabled_name (enabled, action_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共动作主表';

CREATE TABLE IF NOT EXISTS mt_public_action_steps (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  public_action_id BIGINT UNSIGNED NOT NULL COMMENT '所属公共动作 ID，关联 mt_public_actions.id',
  step_order INT NOT NULL COMMENT '步骤顺序，从 1 开始',
  step_action VARCHAR(80) NOT NULL DEFAULT '' COMMENT '步骤动作类型，例如 click、input、optional_click',
  locator_method VARCHAR(80) NOT NULL DEFAULT '' COMMENT '定位方式，例如 text、class、class_text、src、xpath',
  locator_value TEXT NULL COMMENT '定位值，支持 {参数名} 占位',
  locator_options TEXT NULL COMMENT '定位高级参数，例如 tag=view,index=2,parent=class:xxx',
  step_value TEXT NULL COMMENT '步骤附加值，例如输入内容、等待秒数或变量名',
  condition_type VARCHAR(40) NOT NULL DEFAULT 'always' COMMENT '执行条件类型：always/exists/not_exists/page_is/page_contains',
  condition_locator_method VARCHAR(80) NOT NULL DEFAULT '' COMMENT '条件定位方式，留空时可复用步骤定位方式',
  condition_locator_value TEXT NULL COMMENT '条件定位值或页面路径',
  condition_options TEXT NULL COMMENT '条件高级参数，例如 timeout=2',
  child_public_action_id BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '子公共动作 ID，用于公共动作嵌套',
  remark TEXT NULL COMMENT '步骤备注',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_public_action_steps_order (public_action_id, step_order),
  KEY idx_mt_public_action_steps_enabled (public_action_id, enabled, step_order),
  KEY idx_mt_public_action_steps_child_action (child_public_action_id),
  CONSTRAINT fk_mt_public_action_steps_action_id
    FOREIGN KEY (public_action_id)
    REFERENCES mt_public_actions (id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT fk_mt_public_action_steps_child_action
    FOREIGN KEY (child_public_action_id)
    REFERENCES mt_public_actions (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共动作步骤表';

CREATE TABLE IF NOT EXISTS mt_case_steps (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  case_id VARCHAR(80) NOT NULL COMMENT '所属用例编号，关联 mt_cases.case_id',
  step_order INT NOT NULL COMMENT '步骤顺序，从 1 开始',
  step_action VARCHAR(80) NOT NULL DEFAULT '' COMMENT '步骤动作类型，例如 click、input、wait、element_exists',
  locator_method VARCHAR(80) NOT NULL DEFAULT '' COMMENT '定位方式，例如 text、class、class_text、src、xpath',
  locator_value TEXT NULL COMMENT '定位值，支持 {参数名} 占位',
  locator_options TEXT NULL COMMENT '定位高级参数，例如 tag=view,index=2,parent=class:xxx',
  step_value TEXT NULL COMMENT '步骤附加值，例如输入内容、等待秒数或变量名',
  condition_type VARCHAR(40) NOT NULL DEFAULT 'always' COMMENT '执行条件类型：always/exists/not_exists/page_is/page_contains',
  condition_locator_method VARCHAR(80) NOT NULL DEFAULT '' COMMENT '条件定位方式，留空时可复用步骤定位方式',
  condition_locator_value TEXT NULL COMMENT '条件定位值或页面路径',
  condition_options TEXT NULL COMMENT '条件高级参数，例如 timeout=2',
  public_action_id BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '引用的公共动作 ID，非空时执行公共动作',
  remark TEXT NULL COMMENT '步骤备注',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_case_steps_case_order (case_id, step_order),
  KEY idx_mt_case_steps_case_enabled (case_id, enabled, step_order),
  KEY idx_mt_case_steps_public_action_id (public_action_id),
  CONSTRAINT fk_mt_case_steps_case_id
    FOREIGN KEY (case_id)
    REFERENCES mt_cases (case_id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT fk_mt_case_steps_public_action_id
    FOREIGN KEY (public_action_id)
    REFERENCES mt_public_actions (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用例步骤表';

CREATE TABLE IF NOT EXISTS mt_schedules (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  schedule_name VARCHAR(160) NOT NULL COMMENT '定时任务名称',
  case_id VARCHAR(80) NOT NULL DEFAULT '' COMMENT '执行的用例编号，空值表示执行全部用例',
  cron_expr VARCHAR(120) NOT NULL COMMENT 'cron 表达式，例如 0 9 * * *',
  run_target VARCHAR(80) NOT NULL DEFAULT 'center' COMMENT '执行目标，当前默认 center',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
  last_run_at DATETIME NULL COMMENT '上次触发时间',
  next_run_at DATETIME NULL COMMENT '下次触发时间',
  last_job_id VARCHAR(80) NOT NULL DEFAULT '' COMMENT '最近一次执行任务 ID',
  last_status VARCHAR(40) NOT NULL DEFAULT '' COMMENT '最近一次执行状态',
  fail_count INT NOT NULL DEFAULT 0 COMMENT '连续失败次数',
  remark TEXT NULL COMMENT '备注',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  KEY idx_mt_schedules_enabled_next (enabled, next_run_at),
  KEY idx_mt_schedules_case_id (case_id),
  KEY idx_mt_schedules_last_job (last_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='定时任务表';

CREATE TABLE IF NOT EXISTS mt_run_records (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  job_id VARCHAR(80) NOT NULL COMMENT '执行任务 ID',
  case_id VARCHAR(80) NOT NULL DEFAULT '' COMMENT '执行的用例编号，空值表示执行全部用例',
  iteration_id BIGINT UNSIGNED NULL COMMENT '执行的迭代 ID，按迭代执行时关联 mt_iteration.id',
  status ENUM('queued', 'running', 'success', 'failed') NOT NULL DEFAULT 'queued' COMMENT '执行状态',
  trigger_type ENUM('manual', 'schedule') NOT NULL DEFAULT 'manual' COMMENT '触发方式：manual=手动执行，schedule=定时任务',
  schedule_id BIGINT UNSIGNED NULL COMMENT '关联定时任务 ID，手动执行为空',
  assigned_agent_id VARCHAR(120) NOT NULL DEFAULT '' COMMENT '指定执行机标识，空值表示不限',
  assigned_agent_ip VARCHAR(64) NOT NULL DEFAULT '' COMMENT '指定执行机 IP，空值表示不限',
  agent_id VARCHAR(120) NOT NULL DEFAULT '' COMMENT '实际领取并执行任务的执行机标识',
  command_text TEXT NULL COMMENT '实际执行命令',
  returncode INT NULL COMMENT '进程退出码',
  report_url VARCHAR(500) NOT NULL DEFAULT '' COMMENT '报告访问 URL',
  report_dir VARCHAR(500) NOT NULL DEFAULT '' COMMENT '报告本地目录',
  result_summary JSON NULL COMMENT '执行结果汇总 JSON',
  stdout_text MEDIUMTEXT NULL COMMENT '标准输出日志',
  stderr_text MEDIUMTEXT NULL COMMENT '错误输出日志',
  started_at DATETIME NULL COMMENT '执行开始时间',
  finished_at DATETIME NULL COMMENT '执行结束时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_run_records_job_id (job_id),
  KEY idx_mt_run_records_case_time (case_id, created_at),
  KEY idx_mt_run_records_iteration_time (iteration_id, created_at),
  KEY idx_mt_run_records_status_time (status, created_at),
  KEY idx_mt_run_records_trigger_time (trigger_type, created_at),
  KEY idx_mt_run_records_schedule (schedule_id, created_at),
  KEY idx_mt_run_records_agent_queue (status, assigned_agent_ip, assigned_agent_id, created_at),
  KEY idx_mt_run_records_agent_time (agent_id, created_at),
  CONSTRAINT fk_mt_run_records_schedule_id
    FOREIGN KEY (schedule_id)
    REFERENCES mt_schedules (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT fk_mt_run_records_iteration_id
    FOREIGN KEY (iteration_id)
    REFERENCES mt_iteration (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行任务记录表';

CREATE TABLE IF NOT EXISTS mt_agents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  agent_id VARCHAR(120) NOT NULL COMMENT '执行机唯一标识',
  agent_name VARCHAR(120) NOT NULL DEFAULT '' COMMENT '执行机名称',
  agent_ip VARCHAR(64) NOT NULL DEFAULT '' COMMENT '执行机局域网 IP',
  status ENUM('online', 'offline', 'running') NOT NULL DEFAULT 'online' COMMENT '执行机状态',
  current_job_id VARCHAR(80) NOT NULL DEFAULT '' COMMENT '当前执行任务 ID',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否允许接任务：1=允许，0=禁用',
  last_heartbeat_at DATETIME NULL COMMENT '最后心跳时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_agents_agent_id (agent_id),
  KEY idx_mt_agents_ip (agent_ip),
  KEY idx_mt_agents_status_heartbeat (status, last_heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行机登记表';

CREATE TABLE IF NOT EXISTS mt_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键 ID',
  job_id VARCHAR(80) NOT NULL COMMENT '关联执行任务 ID',
  case_id VARCHAR(80) NOT NULL DEFAULT '' COMMENT '关联用例编号，空值表示全部用例或历史报告',
  iteration_id BIGINT UNSIGNED NULL COMMENT '关联迭代 ID，按迭代执行时关联 mt_iteration.id',
  agent_id VARCHAR(120) NOT NULL DEFAULT '' COMMENT '执行机标识',
  report_name VARCHAR(255) NOT NULL DEFAULT '' COMMENT '报告名称',
  status ENUM('queued', 'running', 'success', 'failed') NOT NULL DEFAULT 'success' COMMENT '报告状态',
  trigger_type ENUM('manual', 'schedule') NOT NULL DEFAULT 'manual' COMMENT '触发方式：manual=手动执行，schedule=定时任务',
  schedule_id BIGINT UNSIGNED NULL COMMENT '关联定时任务 ID，手动执行为空',
  total INT NOT NULL DEFAULT 0 COMMENT '用例总数',
  passed INT NOT NULL DEFAULT 0 COMMENT '通过数量',
  failed INT NOT NULL DEFAULT 0 COMMENT '失败数量',
  skipped INT NOT NULL DEFAULT 0 COMMENT '跳过数量',
  duration_seconds DECIMAL(10,3) NULL COMMENT '执行耗时，单位秒',
  report_url VARCHAR(500) NOT NULL DEFAULT '' COMMENT '优先报告访问 URL',
  simple_report_url VARCHAR(500) NOT NULL DEFAULT '' COMMENT '简易报告 URL',
  simple_report_html MEDIUMTEXT NULL COMMENT '简易报告 HTML 内容快照，用于跨机器查看',
  simple_report_size INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '简易报告 HTML 字节数',
  official_report_url VARCHAR(500) NOT NULL DEFAULT '' COMMENT 'minium 原始报告 URL',
  report_dir VARCHAR(500) NOT NULL DEFAULT '' COMMENT '报告本地目录',
  output_dir VARCHAR(500) NOT NULL DEFAULT '' COMMENT '执行输出目录',
  result_summary JSON NULL COMMENT '报告结果汇总 JSON',
  started_at DATETIME NULL COMMENT '执行开始时间',
  finished_at DATETIME NULL COMMENT '执行结束时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_mt_reports_job_id (job_id),
  KEY idx_mt_reports_case_time (case_id, created_at),
  KEY idx_mt_reports_iteration_time (iteration_id, created_at),
  KEY idx_mt_reports_status_time (status, created_at),
  KEY idx_mt_reports_trigger_time (trigger_type, created_at),
  KEY idx_mt_reports_schedule (schedule_id, created_at),
  KEY idx_mt_reports_agent_time (agent_id, created_at),
  CONSTRAINT fk_mt_reports_schedule_id
    FOREIGN KEY (schedule_id)
    REFERENCES mt_schedules (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT fk_mt_reports_iteration_id
    FOREIGN KEY (iteration_id)
    REFERENCES mt_iteration (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='测试报告索引表';

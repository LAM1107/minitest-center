-- 定时任务执行对象从单个用例改为所属迭代。
-- 先执行本迁移，再重启中心服务。保留 case_id 仅用于识别历史任务。
-- 仅对已经存在的旧 mt_schedules 表执行；全新数据库请直接使用 minitest_mysql_schema.sql。
ALTER TABLE mt_schedules
  ADD COLUMN iteration_id BIGINT UNSIGNED NULL COMMENT '执行的迭代 ID，关联 mt_iteration.id' AFTER schedule_name,
  ADD KEY idx_mt_schedules_iteration_id (iteration_id),
  ADD CONSTRAINT fk_mt_schedules_iteration_id
    FOREIGN KEY (iteration_id)
    REFERENCES mt_iteration (id)
    ON DELETE SET NULL
    ON UPDATE CASCADE;

-- 可无歧义映射的旧“单用例”任务迁移到该用例当前所属迭代。
-- 没有迭代归属的任务保持 NULL，页面会要求手动选择迭代，不会执行全部用例。
UPDATE mt_schedules AS s
JOIN mt_cases AS c ON c.case_id = s.case_id
SET s.iteration_id = c.iteration_id
WHERE s.iteration_id IS NULL
  AND s.case_id <> ''
  AND c.iteration_id IS NOT NULL;

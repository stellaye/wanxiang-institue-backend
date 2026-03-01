-- 多级分销系统数据库表创建脚本
-- 数据库: wanxiang

USE wanxiang;

-- 1. 推广关系链表
CREATE TABLE IF NOT EXISTS `referral_chain` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT NOT NULL COMMENT '用户ID',
  `parent_user_id` BIGINT DEFAULT NULL COMMENT '直接上级用户ID',
  `ancestor_path` VARCHAR(1000) NOT NULL DEFAULT '/' COMMENT '祖先路径 /1/5/12/',
  `level` INT NOT NULL DEFAULT 0 COMMENT '层级，0表示顶级',
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_id` (`user_id`),
  KEY `idx_parent_user_id` (`parent_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推广关系链表';

-- 2. 佣金配置表
CREATE TABLE IF NOT EXISTS `commission_config` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `parent_user_id` BIGINT NOT NULL COMMENT '上级用户ID',
  `child_user_id` BIGINT NOT NULL COMMENT '下级用户ID',
  `commission_rate` DECIMAL(5,2) NOT NULL DEFAULT 20.00 COMMENT '给下级的佣金比例%',
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_parent_child` (`parent_user_id`, `child_user_id`),
  KEY `idx_parent_user_id` (`parent_user_id`),
  KEY `idx_child_user_id` (`child_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='佣金配置表';

-- 3. 佣金分配记录表
CREATE TABLE IF NOT EXISTS `commission_record` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `order_no` VARCHAR(64) NOT NULL COMMENT '订单号',
  `user_id` BIGINT NOT NULL COMMENT '获得佣金的用户ID',
  `level` INT NOT NULL COMMENT '在推广链中的层级',
  `commission_amount` INT NOT NULL COMMENT '佣金金额(分)',
  `commission_rate` DECIMAL(5,2) NOT NULL COMMENT '佣金比例%',
  `order_amount` INT NOT NULL COMMENT '订单金额(分)',
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_order_no` (`order_no`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_created_time` (`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='佣金分配记录表';

-- 验证表是否创建成功
SHOW TABLES LIKE '%commission%';
SHOW TABLES LIKE 'referral_chain';

-- 查看表结构
DESC referral_chain;
DESC commission_config;
DESC commission_record;

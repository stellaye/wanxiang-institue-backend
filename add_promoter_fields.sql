-- 为User表添加新字段，支持"只有推广者才算下级"的逻辑
-- 数据库: wanxiang

USE wanxiang;

-- 添加 referred_by 字段：记录注册时的推荐人ref_code
ALTER TABLE `user`
ADD COLUMN `referred_by` VARCHAR(100) NULL COMMENT '推荐人的ref_code（注册时记录）' AFTER `total_earned`;

-- 添加 is_promoter 字段：标记用户是否已成为推广者
ALTER TABLE `user`
ADD COLUMN `is_promoter` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已成为推广者' AFTER `referred_by`;

-- 添加索引
ALTER TABLE `user` ADD INDEX `idx_referred_by` (`referred_by`);
ALTER TABLE `user` ADD INDEX `idx_is_promoter` (`is_promoter`);

-- 验证字段是否添加成功
DESC `user`;

-- 查看现有用户数据
SELECT id, ref_code, referred_by, is_promoter FROM `user` LIMIT 10;

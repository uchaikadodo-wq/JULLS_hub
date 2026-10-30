-- Synthetic test schema only; app user has no global grants.
CREATE DATABASE IF NOT EXISTS `bookstack-test`;
GRANT ALL PRIVILEGES ON `bookstack-test`.* TO 'bookstack-local'@'%';

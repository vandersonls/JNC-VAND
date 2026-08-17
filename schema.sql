-- Schema do sistema de gerenciamento de materiais para Projetos de Engenharia Elétrica
-- Banco: bmt

CREATE DATABASE IF NOT EXISTS bmt CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bmt;

-- =========================================================
-- USUÁRIOS
-- =========================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    senha_hash VARCHAR(255) NOT NULL,
    perfil ENUM('master', 'administrador', 'visualizador') NOT NULL DEFAULT 'visualizador',
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuarios' AND COLUMN_NAME = 'sessao_ultima_atividade');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE usuarios ADD COLUMN sessao_ultima_atividade DATETIME NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Controle de tentativas de login (proteção contra força bruta)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuarios' AND COLUMN_NAME = 'login_falhas');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE usuarios ADD COLUMN login_falhas INT NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuarios' AND COLUMN_NAME = 'login_bloqueado_ate');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE usuarios ADD COLUMN login_bloqueado_ate DATETIME NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =========================================================
-- CLIENTES
-- =========================================================
CREATE TABLE IF NOT EXISTS clientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    razao_social VARCHAR(200) NOT NULL,
    nome_fantasia VARCHAR(200),
    cnpj_cpf VARCHAR(20),
    contato VARCHAR(150),
    telefone VARCHAR(30),
    email VARCHAR(150),
    endereco VARCHAR(255),
    logo_url VARCHAR(500),
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'clientes' AND COLUMN_NAME = 'logo_url');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE clientes ADD COLUMN logo_url VARCHAR(500) AFTER endereco', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =========================================================
-- ÁREAS (disciplinas: Engenharia Elétrica, Mecânica, Civil, etc.)
-- =========================================================
CREATE TABLE IF NOT EXISTS areas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT IGNORE INTO areas (nome) VALUES ('Engenharia Elétrica');

-- =========================================================
-- MATERIAIS
-- =========================================================
CREATE TABLE IF NOT EXISTS materiais (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    descricao VARCHAR(500) NOT NULL,
    fabricante VARCHAR(150),
    bitola VARCHAR(50),
    unidade VARCHAR(20) NOT NULL,
    area_id INT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Migrações idempotentes para bancos já existentes
ALTER TABLE materiais MODIFY COLUMN descricao VARCHAR(500) NOT NULL;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'materiais' AND COLUMN_NAME = 'area_id');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE materiais ADD COLUMN area_id INT NULL AFTER unidade', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill: todo material sem área cai na área padrão (Engenharia Elétrica)
UPDATE materiais SET area_id = (SELECT id FROM areas WHERE nome = 'Engenharia Elétrica') WHERE area_id IS NULL;
ALTER TABLE materiais MODIFY COLUMN area_id INT NOT NULL;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'materiais' AND CONSTRAINT_NAME = 'fk_materiais_area');
SET @sql = IF(@fk_exists = 0,
    'ALTER TABLE materiais ADD CONSTRAINT fk_materiais_area FOREIGN KEY (area_id) REFERENCES areas(id)',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =========================================================
-- PERMISSÕES DE ÁREA POR USUÁRIO (usuários master enxergam tudo, sempre)
-- =========================================================
CREATE TABLE IF NOT EXISTS usuario_areas (
    usuario_id INT NOT NULL,
    area_id INT NOT NULL,
    PRIMARY KEY (usuario_id, area_id),
    CONSTRAINT fk_usuario_areas_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    CONSTRAINT fk_usuario_areas_area FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- =========================================================
-- PROJETOS
-- =========================================================
CREATE TABLE IF NOT EXISTS projetos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    nome VARCHAR(200) NOT NULL,
    cliente_id INT,
    descricao TEXT,
    status ENUM('conceitual', 'basico', 'detalhado') NOT NULL DEFAULT 'conceitual',
    numero_cliente VARCHAR(100),
    numero_fornecedor VARCHAR(100),
    area_id INT NULL,
    pq_versao_atual_id INT NULL,
    compras_versao_atual_id INT NULL,
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_projetos_cliente FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL,
    CONSTRAINT fk_projetos_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL,
    CONSTRAINT fk_projetos_area FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Migrações idempotentes para bancos já existentes
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND COLUMN_NAME = 'numero_cliente');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE projetos ADD COLUMN numero_cliente VARCHAR(100) AFTER status', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND COLUMN_NAME = 'numero_fornecedor');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE projetos ADD COLUMN numero_fornecedor VARCHAR(100) AFTER numero_cliente', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND COLUMN_NAME = 'area_id');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE projetos ADD COLUMN area_id INT NULL AFTER numero_fornecedor', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND CONSTRAINT_NAME = 'fk_projetos_area');
SET @sql = IF(@fk_exists = 0, 'ALTER TABLE projetos ADD CONSTRAINT fk_projetos_area FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND COLUMN_NAME = 'pq_versao_atual_id');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE projetos ADD COLUMN pq_versao_atual_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND COLUMN_NAME = 'compras_versao_atual_id');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE projetos ADD COLUMN compras_versao_atual_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Migra o status de "andamento" (planejamento/em_andamento/concluido/cancelado)
-- para "fase de engenharia" (conceitual/basico/detalhado). Alarga o enum pra
-- caber os dois conjuntos, remapeia os valores antigos e só depois estreita
-- pro conjunto novo - assim é seguro rodar de novo em bancos já migrados
-- (a 2ª execução não encontra nenhum valor antigo pra remapear).
ALTER TABLE projetos MODIFY COLUMN status
    ENUM('planejamento', 'em_andamento', 'concluido', 'cancelado', 'conceitual', 'basico', 'detalhado')
    NOT NULL DEFAULT 'conceitual';
UPDATE projetos SET status = CASE status
    WHEN 'planejamento' THEN 'conceitual'
    WHEN 'em_andamento' THEN 'detalhado'
    WHEN 'concluido' THEN 'detalhado'
    WHEN 'cancelado' THEN 'conceitual'
    ELSE status END;
ALTER TABLE projetos MODIFY COLUMN status ENUM('conceitual', 'basico', 'detalhado') NOT NULL DEFAULT 'conceitual';

-- =========================================================
-- LISTAS POR DESENHO (cabeçalho lógico - agrupa versões)
-- =========================================================
CREATE TABLE IF NOT EXISTS listas_desenho (
    id INT AUTO_INCREMENT PRIMARY KEY,
    projeto_id INT NOT NULL,
    numero_desenho VARCHAR(100) NOT NULL,
    titulo VARCHAR(200),
    subtitulo VARCHAR(200),
    area_titulo VARCHAR(200),
    disciplina VARCHAR(100),
    numero_cliente VARCHAR(100),
    numero_fornecedor VARCHAR(100),
    rev_manual INT NULL,
    data_emissao_manual DATE NULL,
    elaborador_nome VARCHAR(150),
    elaborador_sigla VARCHAR(20),
    verificador_nome VARCHAR(150),
    verificador_sigla VARCHAR(20),
    aprovador_nome VARCHAR(150),
    aprovador_sigla VARCHAR(20),
    autorizado_nome VARCHAR(150),
    autorizado_sigla VARCHAR(20),
    versao_atual_id INT NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_lista_projeto FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE,
    UNIQUE KEY uq_projeto_desenho (projeto_id, numero_desenho)
) ENGINE=InnoDB;

-- Migração idempotente para bancos já existentes (schema.sql acima cobre instalações novas)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'numero_cliente');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN numero_cliente VARCHAR(100) AFTER titulo', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'numero_fornecedor');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN numero_fornecedor VARCHAR(100) AFTER numero_cliente', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Rev. e Data de emissão preenchidos manualmente no cabeçalho (o operador
-- confere com a última revisão registrada) - por enquanto não substituem o
-- número de versão automático do sistema, só o que aparece impresso.
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'rev_manual');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN rev_manual INT NULL AFTER numero_fornecedor', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'data_emissao_manual');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN data_emissao_manual DATE NULL AFTER rev_manual', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Campos de carimbo/aprovação (elaborador, verificador, aprovador - nome e sigla)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'elaborador_nome');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN elaborador_nome VARCHAR(150) AFTER numero_fornecedor', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'elaborador_sigla');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN elaborador_sigla VARCHAR(20) AFTER elaborador_nome', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'verificador_nome');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN verificador_nome VARCHAR(150) AFTER elaborador_sigla', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'verificador_sigla');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN verificador_sigla VARCHAR(20) AFTER verificador_nome', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'aprovador_nome');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN aprovador_nome VARCHAR(150) AFTER verificador_sigla', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'aprovador_sigla');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN aprovador_sigla VARCHAR(20) AFTER aprovador_nome', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Bloco de título em 4 linhas (subtítulo de engenharia / área / disciplina
-- / título) e assinatura de autorização, pra bater com o carimbo padrão
-- de documentos de engenharia usado como modelo de impressão.
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'subtitulo');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN subtitulo VARCHAR(200) AFTER titulo', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'area_titulo');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN area_titulo VARCHAR(200) AFTER subtitulo', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'disciplina');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN disciplina VARCHAR(100) AFTER area_titulo', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'autorizado_nome');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN autorizado_nome VARCHAR(150) AFTER aprovador_sigla', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'listas_desenho' AND COLUMN_NAME = 'autorizado_sigla');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE listas_desenho ADD COLUMN autorizado_sigla VARCHAR(20) AFTER autorizado_nome', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =========================================================
-- VERSÕES DA LISTA POR DESENHO (histórico imutável)
-- =========================================================
CREATE TABLE IF NOT EXISTS lista_desenho_versoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lista_desenho_id INT NOT NULL,
    versao INT NOT NULL,
    status ENUM('rascunho', 'salvo') NOT NULL DEFAULT 'salvo',
    tipo_emissao ENUM('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H') NULL,
    observacoes TEXT,
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_versao_lista FOREIGN KEY (lista_desenho_id) REFERENCES listas_desenho(id) ON DELETE CASCADE,
    CONSTRAINT fk_versao_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL,
    UNIQUE KEY uq_lista_versao (lista_desenho_id, versao)
) ENGINE=InnoDB;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lista_desenho_versoes' AND COLUMN_NAME = 'tipo_emissao');
SET @sql = IF(@col_exists = 0, "ALTER TABLE lista_desenho_versoes ADD COLUMN tipo_emissao ENUM('A','B','C','D','E','F','G','H') NULL AFTER status", 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

ALTER TABLE listas_desenho
    ADD CONSTRAINT fk_lista_versao_atual FOREIGN KEY (versao_atual_id) REFERENCES lista_desenho_versoes(id) ON DELETE SET NULL;

-- =========================================================
-- ITENS DE CADA VERSÃO DA LISTA (materiais utilizados no desenho)
-- =========================================================
CREATE TABLE IF NOT EXISTS lista_desenho_itens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    versao_id INT NOT NULL,
    material_id INT NOT NULL,
    quantidade DECIMAL(12,3) NOT NULL DEFAULT 0,
    observacao VARCHAR(255),
    CONSTRAINT fk_item_versao FOREIGN KEY (versao_id) REFERENCES lista_desenho_versoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_item_material FOREIGN KEY (material_id) REFERENCES materiais(id)
) ENGINE=InnoDB;

-- =========================================================
-- LISTA PQ (percentual sobre a última versão consolidada da Lista por
-- Desenho do projeto) - uma por projeto, com histórico de versões
-- =========================================================
CREATE TABLE IF NOT EXISTS lista_pq_versoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    projeto_id INT NOT NULL,
    versao INT NOT NULL,
    status ENUM('rascunho', 'salvo') NOT NULL DEFAULT 'salvo',
    observacoes TEXT,
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pq_versao_projeto FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE,
    CONSTRAINT fk_pq_versao_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL,
    UNIQUE KEY uq_pq_projeto_versao (projeto_id, versao)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lista_pq_itens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    versao_id INT NOT NULL,
    material_id INT NOT NULL,
    quantidade_base DECIMAL(12,3) NOT NULL DEFAULT 0,
    percentual DECIMAL(7,3) NOT NULL DEFAULT 0,
    quantidade_atualizada DECIMAL(12,3) NOT NULL DEFAULT 0,
    observacao VARCHAR(255),
    CONSTRAINT fk_pq_item_versao FOREIGN KEY (versao_id) REFERENCES lista_pq_versoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_pq_item_material FOREIGN KEY (material_id) REFERENCES materiais(id)
) ENGINE=InnoDB;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND CONSTRAINT_NAME = 'fk_projetos_pq_versao');
SET @sql = IF(@fk_exists = 0,
    'ALTER TABLE projetos ADD CONSTRAINT fk_projetos_pq_versao FOREIGN KEY (pq_versao_atual_id) REFERENCES lista_pq_versoes(id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Rastreabilidade: registra, para cada versão da Lista PQ, quais listas por
-- desenho (e qual versão de cada uma) foram usadas para montá-la.
CREATE TABLE IF NOT EXISTS lista_pq_origens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pq_versao_id INT NOT NULL,
    lista_desenho_id INT NOT NULL,
    lista_desenho_versao_id INT NOT NULL,
    numero_desenho VARCHAR(100) NOT NULL,
    titulo VARCHAR(255),
    versao_numero INT NOT NULL,
    CONSTRAINT fk_pq_origem_versao FOREIGN KEY (pq_versao_id) REFERENCES lista_pq_versoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_pq_origem_lista FOREIGN KEY (lista_desenho_id) REFERENCES listas_desenho(id) ON DELETE CASCADE,
    CONSTRAINT fk_pq_origem_lista_versao FOREIGN KEY (lista_desenho_versao_id) REFERENCES lista_desenho_versoes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- =========================================================
-- LISTA DE COMPRAS (derivada da última versão da Lista PQ do projeto)
-- =========================================================
CREATE TABLE IF NOT EXISTS lista_compras_versoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    projeto_id INT NOT NULL,
    versao INT NOT NULL,
    status ENUM('rascunho', 'salvo') NOT NULL DEFAULT 'salvo',
    observacoes TEXT,
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pq_versao_id INT NULL,
    CONSTRAINT fk_compras_versao_projeto FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE,
    CONSTRAINT fk_compras_versao_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL,
    UNIQUE KEY uq_compras_projeto_versao (projeto_id, versao)
) ENGINE=InnoDB;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lista_compras_versoes' AND COLUMN_NAME = 'pq_versao_id');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE lista_compras_versoes ADD COLUMN pq_versao_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lista_compras_versoes' AND CONSTRAINT_NAME = 'fk_compras_versao_pq');
SET @sql = IF(@fk_exists = 0,
    'ALTER TABLE lista_compras_versoes ADD CONSTRAINT fk_compras_versao_pq FOREIGN KEY (pq_versao_id) REFERENCES lista_pq_versoes(id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS lista_compras_itens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    versao_id INT NOT NULL,
    material_id INT NOT NULL,
    quantidade DECIMAL(12,3) NOT NULL DEFAULT 0,
    observacao VARCHAR(255),
    CONSTRAINT fk_compras_item_versao FOREIGN KEY (versao_id) REFERENCES lista_compras_versoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_compras_item_material FOREIGN KEY (material_id) REFERENCES materiais(id)
) ENGINE=InnoDB;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projetos' AND CONSTRAINT_NAME = 'fk_projetos_compras_versao');
SET @sql = IF(@fk_exists = 0,
    'ALTER TABLE projetos ADD CONSTRAINT fk_projetos_compras_versao FOREIGN KEY (compras_versao_atual_id) REFERENCES lista_compras_versoes(id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =========================================================
-- CONFIGURAÇÕES DO SISTEMA (chave/valor)
-- =========================================================
CREATE TABLE IF NOT EXISTS configuracoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chave VARCHAR(100) NOT NULL UNIQUE,
    valor TEXT,
    descricao VARCHAR(255),
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT IGNORE INTO configuracoes (chave, valor, descricao) VALUES
    ('nome_empresa', 'NJC Engenharia Elétrica', 'Nome exibido no sistema'),
    ('logo_url', '', 'URL/caminho do logotipo'),
    ('formato_data', 'DD/MM/YYYY', 'Formato de exibição de datas');

-- =========================================================
-- AUDITORIA (quem fez o quê, e quando)
-- =========================================================
CREATE TABLE IF NOT EXISTS auditoria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NULL,
    usuario_nome VARCHAR(150) NOT NULL,
    acao ENUM('criar', 'editar', 'excluir', 'importar', 'login', 'logout', 'exportar', 'encerrar_sessao') NOT NULL,
    entidade VARCHAR(50) NOT NULL,
    entidade_id INT NULL,
    descricao VARCHAR(500) NOT NULL,
    dados_antes JSON NULL,
    dados_depois JSON NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_auditoria_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL,
    INDEX idx_auditoria_entidade (entidade),
    INDEX idx_auditoria_criado_em (criado_em)
) ENGINE=InnoDB;

-- Redefinir o ENUM é seguro de reexecutar (mesma definição não gera erro).
ALTER TABLE auditoria MODIFY COLUMN acao ENUM('criar', 'editar', 'excluir', 'importar', 'login', 'logout', 'exportar', 'encerrar_sessao') NOT NULL;

-- Usuário master inicial (senha: admin123 - troque após o primeiro login)
-- Hash gerado com werkzeug.security.generate_password_hash em tempo de execução (ver seed.py)

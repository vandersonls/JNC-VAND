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
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =========================================================
-- MATERIAIS
-- =========================================================
CREATE TABLE IF NOT EXISTS materiais (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    descricao VARCHAR(255) NOT NULL,
    fabricante VARCHAR(150),
    bitola VARCHAR(50),
    unidade VARCHAR(20) NOT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
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
    status ENUM('planejamento', 'em_andamento', 'concluido', 'cancelado') NOT NULL DEFAULT 'planejamento',
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_projetos_cliente FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL,
    CONSTRAINT fk_projetos_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- =========================================================
-- LISTAS POR DESENHO (cabeçalho lógico - agrupa versões)
-- =========================================================
CREATE TABLE IF NOT EXISTS listas_desenho (
    id INT AUTO_INCREMENT PRIMARY KEY,
    projeto_id INT NOT NULL,
    numero_desenho VARCHAR(100) NOT NULL,
    titulo VARCHAR(200),
    versao_atual_id INT NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_lista_projeto FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE,
    UNIQUE KEY uq_projeto_desenho (projeto_id, numero_desenho)
) ENGINE=InnoDB;

-- =========================================================
-- VERSÕES DA LISTA POR DESENHO (histórico imutável)
-- =========================================================
CREATE TABLE IF NOT EXISTS lista_desenho_versoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lista_desenho_id INT NOT NULL,
    versao INT NOT NULL,
    status ENUM('rascunho', 'salvo') NOT NULL DEFAULT 'salvo',
    observacoes TEXT,
    criado_por INT,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_versao_lista FOREIGN KEY (lista_desenho_id) REFERENCES listas_desenho(id) ON DELETE CASCADE,
    CONSTRAINT fk_versao_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL,
    UNIQUE KEY uq_lista_versao (lista_desenho_id, versao)
) ENGINE=InnoDB;

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
    ('nome_empresa', 'BTM Engenharia Elétrica', 'Nome exibido no sistema'),
    ('logo_url', '', 'URL/caminho do logotipo'),
    ('formato_data', 'DD/MM/YYYY', 'Formato de exibição de datas');

-- Usuário master inicial (senha: admin123 - troque após o primeiro login)
-- Hash gerado com werkzeug.security.generate_password_hash em tempo de execução (ver seed.py)

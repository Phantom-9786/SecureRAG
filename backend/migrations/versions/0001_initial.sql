CREATE TABLE categories (
	name VARCHAR(80) NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_categories PRIMARY KEY (id), 
	CONSTRAINT uq_categories_name UNIQUE (name)
);

CREATE TABLE permissions (
	code VARCHAR(80) NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE TABLE roles (
	name VARCHAR(60) NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_roles PRIMARY KEY (id), 
	CONSTRAINT uq_roles_name UNIQUE (name)
);

CREATE TABLE role_category_access (
	role_id UUID NOT NULL, 
	category_id UUID NOT NULL, 
	CONSTRAINT pk_role_category_access PRIMARY KEY (role_id, category_id), 
	CONSTRAINT fk_role_category_access_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_role_category_access_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE
);

CREATE INDEX ix_role_category_access_category_id ON role_category_access (category_id);

CREATE TABLE role_permissions (
	role_id UUID NOT NULL, 
	permission_id UUID NOT NULL, 
	CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
	CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
);

CREATE INDEX ix_role_permissions_permission_id ON role_permissions (permission_id);

CREATE TABLE users (
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role_id UUID NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	token_version INTEGER DEFAULT 0 NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT ck_users_normalized_email CHECK (email = lower(trim(email))), 
	CONSTRAINT ck_users_nonnegative_token_version CHECK (token_version >= 0), 
	CONSTRAINT uq_users_email UNIQUE (email), 
	CONSTRAINT fk_users_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id)
);

CREATE INDEX ix_users_role_id ON users (role_id);

CREATE TABLE conversations (
	user_id UUID NOT NULL, 
	title VARCHAR(200) DEFAULT 'New conversation' NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_conversations PRIMARY KEY (id), 
	CONSTRAINT fk_conversations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_conversations_user_id ON conversations (user_id);

CREATE TABLE documents (
	title VARCHAR(255) NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	storage_key VARCHAR(500) NOT NULL, 
	category_id UUID NOT NULL, 
	uploaded_by UUID NOT NULL, 
	active BOOLEAN DEFAULT false NOT NULL, 
	ingestion_status VARCHAR(20) DEFAULT 'processing' NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_documents PRIMARY KEY (id), 
	CONSTRAINT ck_documents_valid_ingestion_status CHECK (ingestion_status IN ('processing', 'ready', 'failed')), 
	CONSTRAINT uq_documents_storage_key UNIQUE (storage_key), 
	CONSTRAINT fk_documents_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
	CONSTRAINT fk_documents_uploaded_by_users FOREIGN KEY(uploaded_by) REFERENCES users (id)
);

CREATE INDEX ix_documents_category_id ON documents (category_id);

CREATE INDEX ix_documents_uploaded_by ON documents (uploaded_by);

CREATE TABLE chunks (
	document_id UUID NOT NULL, 
	chunk_index INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	page_number INTEGER NOT NULL, 
	embedding VECTOR(1536) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_chunks PRIMARY KEY (id), 
	CONSTRAINT uq_chunks_document_id UNIQUE (document_id, chunk_index), 
	CONSTRAINT ck_chunks_positive_page CHECK (page_number > 0), 
	CONSTRAINT ck_chunks_nonnegative_chunk_index CHECK (chunk_index >= 0), 
	CONSTRAINT ck_chunks_nonempty_content CHECK (length(trim(content)) > 0), 
	CONSTRAINT fk_chunks_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id)
);

CREATE INDEX ix_chunks_document_id ON chunks (document_id);

CREATE TABLE messages (
	conversation_id UUID NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_messages PRIMARY KEY (id), 
	CONSTRAINT ck_messages_valid_role CHECK (role IN ('user', 'assistant')), 
	CONSTRAINT fk_messages_conversation_id_conversations FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_conversation_created ON messages (conversation_id, created_at, id);

CREATE TABLE message_sources (
	message_id UUID NOT NULL, 
	chunk_id UUID NOT NULL, 
	source_number INTEGER NOT NULL, 
	CONSTRAINT pk_message_sources PRIMARY KEY (message_id, chunk_id), 
	CONSTRAINT uq_message_sources_message_id UNIQUE (message_id, source_number), 
	CONSTRAINT ck_message_sources_positive_source_number CHECK (source_number > 0), 
	CONSTRAINT fk_message_sources_message_id_messages FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	CONSTRAINT fk_message_sources_chunk_id_chunks FOREIGN KEY(chunk_id) REFERENCES chunks (id)
);

CREATE INDEX ix_message_sources_chunk_id ON message_sources (chunk_id);

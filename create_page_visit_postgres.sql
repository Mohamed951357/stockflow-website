CREATE TABLE IF NOT EXISTS page_visit (
    id SERIAL PRIMARY KEY,
    page_path VARCHAR(120) NOT NULL,
    visitor_key VARCHAR(160) NOT NULL,
    ip_address VARCHAR(80),
    user_agent TEXT,
    referrer TEXT,
    is_bot BOOLEAN NOT NULL DEFAULT false,
    visit_date DATE NOT NULL DEFAULT CURRENT_DATE,
    visited_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_page_visit_page_path ON page_visit (page_path);
CREATE INDEX IF NOT EXISTS ix_page_visit_visitor_key ON page_visit (visitor_key);
CREATE INDEX IF NOT EXISTS ix_page_visit_visit_date ON page_visit (visit_date);
CREATE INDEX IF NOT EXISTS ix_page_visit_visited_at ON page_visit (visited_at);
CREATE INDEX IF NOT EXISTS ix_page_visit_path_visited_at ON page_visit (page_path, visited_at);
CREATE INDEX IF NOT EXISTS ix_page_visit_path_visitor ON page_visit (page_path, visitor_key);

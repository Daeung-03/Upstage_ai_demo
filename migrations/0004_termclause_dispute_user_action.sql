-- migrations/0004_termclause_dispute_user_action.sql
ALTER TABLE term_clauses ADD COLUMN dispute_user_action TEXT NULL;

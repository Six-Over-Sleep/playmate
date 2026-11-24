BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.fn_sync_game_category_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    CASE NEW.category_code
        WHEN 'PYTHON' THEN
            NEW.category_name := 'Python';
            NEW.category_sort_order := 10;
        WHEN 'SQL' THEN
            NEW.category_name := 'SQL';
            NEW.category_sort_order := 20;
        WHEN 'FRONTEND' THEN
            NEW.category_name := 'Frontend';
            NEW.category_sort_order := 30;
        WHEN 'CS' THEN
            NEW.category_name := 'Computer Science';
            NEW.category_sort_order := 40;
        WHEN 'AI' THEN
            NEW.category_name := 'Artificial Intelligence';
            NEW.category_sort_order := 50;
        WHEN 'GENERAL' THEN
            -- UTF-8 hex for the Korean category name
            NEW.category_name := convert_from(
                decode('ebafb8eb8b88eab28cec9e84', 'hex'),
                'UTF8'
            );
            NEW.category_sort_order := 60;
        ELSE
            RAISE EXCEPTION 'Unknown category: %',
                NEW.category_code
                USING ERRCODE = '23514';
    END CASE;

    RETURN NEW;
END;
$$;

COMMIT;

-- Issue #176 / Event question JSONB integrity
-- PostgreSQL 18 / Local Docker test DB only

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

-- 이벤트 문제 구성 검증
CREATE FUNCTION public.fn_validate_event_questions_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    item JSONB;
    question_id_value BIGINT;
    order_value INTEGER;
    points_value INTEGER;
    question_game_id BIGINT;
    seen_questions BIGINT[] := ARRAY[]::BIGINT[];
    seen_orders INTEGER[] := ARRAY[]::INTEGER[];
BEGIN
    IF jsonb_typeof(NEW.question_set) <> 'array'
       OR jsonb_array_length(NEW.question_set) > 200 THEN
        RAISE EXCEPTION 'Invalid event question set'
            USING ERRCODE = '23514';
    END IF;

    FOR item IN
        SELECT value
        FROM jsonb_array_elements(NEW.question_set)
    LOOP
        IF jsonb_typeof(item) <> 'object'
           OR NOT (item ?& ARRAY[
               'question_id', 'display_order', 'points'
           ])
           OR (SELECT COUNT(*) FROM jsonb_object_keys(item)) <> 3
           OR jsonb_typeof(item->'question_id') <> 'number'
           OR jsonb_typeof(item->'display_order') <> 'number'
           OR jsonb_typeof(item->'points') <> 'number'
        THEN
            RAISE EXCEPTION 'Invalid question item'
                USING ERRCODE = '23514';
        END IF;

        -- 정수로 표현된 값만 허용
        IF (item->>'question_id') !~ '^[0-9]+$'
           OR (item->>'display_order') !~ '^[0-9]+$'
           OR (item->>'points') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Question fields must be integers'
                USING ERRCODE = '23514';
        END IF;

        question_id_value := (item->>'question_id')::BIGINT;
        order_value := (item->>'display_order')::INTEGER;
        points_value := (item->>'points')::INTEGER;

        IF question_id_value <= 0
           OR order_value <= 0
           OR points_value <= 0
           OR question_id_value = ANY(seen_questions)
           OR order_value = ANY(seen_orders) THEN
            RAISE EXCEPTION 'Invalid or duplicate event question'
                USING ERRCODE = '23514';
        END IF;

        SELECT q.game_id
        INTO question_game_id
        FROM public.game_questions AS q
        WHERE q.question_id = question_id_value
        FOR KEY SHARE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Question does not exist: %',
                question_id_value
                USING ERRCODE = '23503';
        END IF;

        IF NEW.game_id IS NOT NULL
           AND question_game_id <> NEW.game_id THEN
            RAISE EXCEPTION 'Question belongs to another game'
                USING ERRCODE = '23514';
        END IF;

        seen_questions := array_append(
            seen_questions, question_id_value
        );
        seen_orders := array_append(
            seen_orders, order_value
        );
    END LOOP;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_event_questions_176
BEFORE INSERT OR UPDATE OF question_set, game_id
ON public.game_events
FOR EACH ROW
EXECUTE FUNCTION public.fn_validate_event_questions_176();

-- JSONB에 참조된 문제 삭제·게임 변경 방지
CREATE FUNCTION public.fn_protect_event_question_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.question_id = OLD.question_id
       AND NEW.game_id = OLD.game_id THEN
        RETURN NEW;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.game_events AS e
        WHERE e.question_set @> jsonb_build_array(
            jsonb_build_object('question_id', OLD.question_id)
        )
    ) THEN
        RAISE EXCEPTION
            'Question is referenced by an event'
            USING ERRCODE = '23503';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_event_question_176
BEFORE DELETE OR UPDATE OF question_id, game_id
ON public.game_questions
FOR EACH ROW
EXECUTE FUNCTION public.fn_protect_event_question_176();

CREATE INDEX IF NOT EXISTS idx_game_events_question_set_176
ON public.game_events
USING GIN (question_set jsonb_path_ops);

COMMIT;

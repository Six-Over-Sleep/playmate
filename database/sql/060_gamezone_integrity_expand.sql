-- Issue #176 / GameZone integrity constraints
-- PostgreSQL 18 / Local Docker test database only
-- Existing foreign keys and tables are preserved.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. 대상 DB 검증
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;
END $$;

-- 2. 게임 카테고리 검증
ALTER TABLE public.games
ADD CONSTRAINT chk_games_category_code_176
CHECK (
    category_code IN (
        'PYTHON',
        'SQL',
        'FRONTEND',
        'CS',
        'AI',
        'GENERAL'
    )
);

ALTER TABLE public.game_questions
ADD CONSTRAINT chk_game_questions_category_code_176
CHECK (
    category_code IN (
        'PYTHON',
        'SQL',
        'FRONTEND',
        'CS',
        'AI',
        'GENERAL'
    )
);

-- 3. 경기 생성 시 지원 모드 확인
CREATE OR REPLACE FUNCTION public.fn_validate_game_mode_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    allowed_modes TEXT[];
BEGIN
    -- 동시 수정 방지를 위해 게임 행에 공유 잠금
    SELECT g.supported_modes
    INTO allowed_modes
    FROM public.games AS g
    WHERE g.game_id = NEW.game_id
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Game does not exist: %', NEW.game_id
            USING ERRCODE = '23503';
    END IF;

    IF NOT (NEW.game_mode = ANY(allowed_modes)) THEN
        RAISE EXCEPTION
            'Unsupported game mode: game_id=%, mode=%',
            NEW.game_id, NEW.game_mode
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_game_mode_176
BEFORE INSERT OR UPDATE OF game_id, game_mode
ON public.game_matches
FOR EACH ROW
EXECUTE FUNCTION public.fn_validate_game_mode_176();

-- 4. 이미 사용 중인 게임 모드 제거 방지
CREATE OR REPLACE FUNCTION public.fn_protect_game_modes_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_matches AS m
        WHERE m.game_id = OLD.game_id
          AND NOT (
              m.game_mode = ANY(NEW.supported_modes)
          )
    ) THEN
        RAISE EXCEPTION
            'Cannot remove a game mode used by existing matches'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_game_modes_176
BEFORE UPDATE OF supported_modes
ON public.games
FOR EACH ROW
EXECUTE FUNCTION public.fn_protect_game_modes_176();

COMMIT;

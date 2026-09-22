from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


MAX_ATTEMPTS = 3


def retry_on_transient(*exception_types: type[BaseException]):
    """Retry a provider call on transient upstream failures.

    Hosted models return 5xx under load often enough that a single attempt
    makes the whole endpoint look broken -- the free tiers especially. Only
    server-side errors are retried; a bad request or an exhausted quota will
    fail the same way however many times it is sent.
    """
    return retry(
        retry=retry_if_exception_type(exception_types),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )

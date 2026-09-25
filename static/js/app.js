const audioPlayers = [...document.querySelectorAll('audio')];

audioPlayers.forEach((player) => {
    player.addEventListener('play', () => {
        audioPlayers.forEach((otherPlayer) => {
            if (otherPlayer !== player) otherPlayer.pause();
        });
    });
});

document.querySelectorAll('.song-card').forEach((card) => {
    const toggle = card.querySelector('.rate-toggle');
    const form = card.querySelector('.rating-form');
    if (!toggle || !form) return;

    const stars = [...form.querySelectorAll('.star-choice')];
    let selectedStars = 0;
    toggle.addEventListener('click', () => {
        form.hidden = !form.hidden;
        if (!form.hidden) stars[0].focus();
    });
    stars.forEach((star) => {
        star.addEventListener('mouseenter', () => paintStars(Number(star.dataset.stars)));
        star.addEventListener('focus', () => paintStars(Number(star.dataset.stars)));
        star.addEventListener('click', () => {
            selectedStars = Number(star.dataset.stars);
            paintStars(selectedStars);
        });
    });
    form.addEventListener('mouseleave', () => paintStars(selectedStars));
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const message = form.querySelector('.form-message');
        if (!selectedStars) { message.textContent = 'Choose a star rating first.'; return; }
        message.textContent = 'Saving...';
        try {
            const response = await fetch(`/songs/${card.dataset.songId}/rating`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({stars: selectedStars, review_text: form.review_text.value})
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Could not save rating.');
            card.querySelector('.average-rating').textContent = result.avg_rating.toFixed(1);
            card.querySelector('.rating-count').textContent = `${result.rating_count} rating${result.rating_count === 1 ? '' : 's'}`;
            message.textContent = 'Rating saved.';
        } catch (error) { message.textContent = error.message; }
    });

    function paintStars(count) {
        stars.forEach((item) => item.classList.toggle('selected', Number(item.dataset.stars) <= count));
    }
});

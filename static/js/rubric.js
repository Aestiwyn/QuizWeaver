// Rubric delete confirmation
(function() {
    var deleteBtn = document.getElementById('delete-rubric-btn');
    if (!deleteBtn) return;

    deleteBtn.addEventListener('click', function() {
        var rubricId = this.getAttribute('data-rubric-id');
        if (!confirm('确定删除这份评分标准吗？')) return;

        fetch('/api/rubrics/' + rubricId, {method: 'DELETE'})
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (data.ok) {
                    // Find the quiz link and go back to quiz, or go to quizzes list
                    var quizLink = document.querySelector('.quiz-info a[href^="/quizzes/"]');
                    if (quizLink) {
                        window.location.href = quizLink.getAttribute('href');
                    } else {
                        window.location.href = '/quizzes';
                    }
                } else {
                    alert('删除失败：' + (data.error || '未知错误'));
                }
            })
            .catch(function(err) {
                alert('删除失败：' + err.message);
            });
    });
})();

